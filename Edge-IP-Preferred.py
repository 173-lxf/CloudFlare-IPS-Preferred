import os
import ipaddress
import ssl
import socket
import sys
import random
import time
import configparser
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor,as_completed



PORT = 443
TIMEOUT = 1
TEST_TIMES = 2
MAX_LOSS = 0.3

DOWNLOAD_SIZE = 200 * 1024
HOST = "speed.cloudflare.com"

#exe路径 .py__file__
BASE_DIR = os.path.dirname(sys.executable)
file_v4path = os.path.join(BASE_DIR, 'ipv4.txt')

config = configparser.ConfigParser()
config_path = os.path.join(BASE_DIR, 'config.ini')
config.read(config_path,encoding='utf8')
MAX_IPS = int(config['settings']['MAX_IPS'])
MAX_NUMBER = int(config['settings']['MAX_NUMBER'])
THREADS = int(config['settings']['THREADS'])
TOP_N = int(config['settings']['TOP_N'])
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def expand(file_path):

    ips = []
    try:
        with open(file_path,'r',encoding='utf8') as file:
            for line in file:
                cidr = line.strip()
                if not cidr:
                    continue
                try:
                    network = ipaddress.ip_network(cidr,strict=False)
                    if isinstance(network, ipaddress.IPv4Network):
                        usable_ips = network.num_addresses - 2
                        if usable_ips <= 0:
                            continue
                        start = int(network.network_address) + 1
                        end = int(network.broadcast_address) - 1
                        usable_ips = network.num_addresses
                        start = int(network.network_address)
                        end = int(network.broadcast_address)

                    sample_size = min(MAX_NUMBER, usable_ips)

                    selected = set()
                    while len(selected) < sample_size:
                        rand_ip = random.randint(start, end)
                        selected.add(str(ipaddress.ip_address(rand_ip)))

                    ips.extend(selected)

                except ValueError as e:
                    print(f"跳过无效CIDR {cidr}：{e}")
    except Exception as e:
        print(f"读取文件 {file_path} 出错：{e}")
    return ips


def speed_test(ip):

    tcp_list = []
    tls_list = []
    ttfb_list = []
    speed_list = []
    tcp_fail = 0

    for _ in range(TEST_TIMES):

        sock = None
        ssock = None
        try:
            #------TCP 测延迟（必须成功）------
            t0 = time.perf_counter()
            sock = socket.create_connection((ip, PORT), timeout=TIMEOUT)
            tcp = (time.perf_counter() - t0) * 1000
            tcp_list.append(tcp)

            # ------TLS + 下载测速（可选，失败不影响结果）------
            try:
                ssock = ctx.wrap_socket(
                    sock,
                    server_hostname=HOST,
                    do_handshake_on_connect=False)
                ssock.settimeout(TIMEOUT)

                t1 = time.perf_counter()
                ssock.do_handshake()
                tls = (time.perf_counter() - t1) * 1000
                tls_list.append(tls)

                # ------TTFB------
                request = (
                    f"GET /__down?bytes={DOWNLOAD_SIZE} HTTP/1.1\r\n"
                    f"Host: {HOST}\r\n"
                    f"Connection: close\r\n\r\n"
                )

                t2 = time.perf_counter()
                ssock.sendall(request.encode())
                first_byte = ssock.recv(1)
                ttfb = ((time.perf_counter() - t2)) * 1000
                ttfb_list.append(ttfb)

                # ------DOWNLOAD_SPEED-----
                total = len(first_byte)
                start_dl = time.perf_counter()

                while total < DOWNLOAD_SIZE:
                    chunk = ssock.recv(8192)
                    if not chunk:
                        break
                    total += len(chunk)
                duration = time.perf_counter() - start_dl
                if duration > 0:
                    speed = total / duration / (1024 * 1024)
                    speed_list.append(speed)

            except Exception:
                # TLS/下载失败，但 TCP 已成功，继续保留该 IP
                pass

        except Exception:
            tcp_fail += 1
            if tcp_fail >= TEST_TIMES:
                return None
        finally:
            if ssock:
                ssock.close()
            if sock:
                sock.close()

    if not tcp_list:
        return None

    loss = tcp_fail / TEST_TIMES
    if loss > MAX_LOSS:
        return None

    return (
        ip,
        round(sum(tcp_list) / len(tcp_list), 1),
        round(sum(tls_list) / len(tls_list), 1) if tls_list else 0,
        round(sum(ttfb_list) / len(ttfb_list), 1) if ttfb_list else 0,
        round(sum(speed_list) / len(speed_list), 2) if speed_list else 0,
        round(loss, 2),
    )




if __name__ =='__main__':
    print('正在运行，请稍后...')
    expand_ips = expand(file_v4path)
    expand_ips =expand_ips[:MAX_IPS]

    if len(expand_ips) == 0:
        print('\n错误：未生成任何有效IP地址，请检查 ipv4.txt！')
        input('\n按回车键退出程序')
        sys.exit(1)

#并发扫描
    results = []
    start_time = time.time()
    print(f'共加载{len(expand_ips)}个IP,开始测速...')
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = [pool.submit(speed_test,ip) for ip in expand_ips]

        for  f in tqdm(as_completed(futures),
                         total = len(expand_ips),
                         desc = '进度',
                         unit = '个',
                         ncols = 80):
            r = f.result()

            if r:
                ip, tcp, tls, ttfb, speed, loss = r
                tqdm.write(
                    f"[OK] {ip:15} "
                    f"TCP:{tcp:5}ms TLS:{tls:5}ms "
                    f"TTFB:{ttfb:5}ms SPD:{speed:5}MB/s "
                    f"LOSS:{loss}"
                )
                results.append(r)


    # ===== 排序=====
    # 排序: 丢包率 → TCP延迟 → 速度(降序)
    results.sort(key=lambda x: (x[5], x[1], -x[4]))

    if TOP_N > len(results):
        TOP_N = len(results)

    # ===== 输出最优 =====
    print("\n================ 最优 IP ================\n")
    result_file = os.path.join(BASE_DIR, 'result.csv')
    with open(result_file,'w',encoding='utf-8-sig') as file:
        file.write("IP地址,TCP耗时(ms),TLS耗时(ms),TTFB(ms),下载速度(MB/s),丢包率\n")
        if not results:
            print(" 无可用IP")
        else:
            for index,(ip, tcp, tls, ttfb, speed, loss) in enumerate(results[:TOP_N],1):
                line = f"{ip},{tcp},{tls},{ttfb},{speed:.1f},{loss}\n"
                file.write(line)

                print(
                    f"TOP{index:<3} {ip.ljust(20)} "
                    f"TCP:{tcp:5}ms TLS:{tls:5}ms "
                    f"TTFB:{ttfb:5}ms SPD:{speed:5.1f}MB/s "
                    f"LOSS:{loss:<4}"
                )

        print("\n=========================================")
        print(f"完成，用时 {round(time.time() - start_time, 1)} 秒")
        print(f"有效 IP：{len(results)}")
        print(f"最优IP已保存到：{result_file}")
        input('\n按回车键退出程序')
        sys.exit(0)
