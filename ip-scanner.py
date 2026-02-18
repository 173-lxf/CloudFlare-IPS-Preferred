import socket
import ssl
import time
import random
import http.client
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 配置 =================
PORT = 443
TIMEOUT = 1.5
THREADS = 150

TEST_TIMES = 2          # 每IP测试次数（终极版降低次数提升整体速度）
MAX_IPS = 200000          # 最大扫描IP数
MAX_LOSS = 0.5          # 最大丢包率
TOP_N = 100             # 输出最优数量

DOWNLOAD_SIZE = 200 * 1024   # 下载测速大小（200KB，足够判断速度）

IP_FILE = r"D:\ips.txt"
HOST = "cloudflare.com"      # TLS / HTTP 使用的 SNI
# ========================================


# ===== 读取 IP =====
with open(IP_FILE, "r", encoding="utf-8") as f:
    ip_list = [i.strip() for i in f if i.strip()]

if len(ip_list) > MAX_IPS:
    ip_list = random.sample(ip_list, MAX_IPS)

print(f"开始扫描 {len(ip_list)} 个 IP...\n")


# ===== 测试函数 =====
def test_ip(ip):
    tcp_list = []
    tls_list = []
    ttfb_list = []
    speed_list = []
    fail = 0

    for _ in range(TEST_TIMES):
        try:
            # ---------- TCP ----------
            t0 = time.time()
            sock = socket.create_connection((ip, PORT), timeout=TIMEOUT)
            tcp = (time.time() - t0) * 1000

            # ---------- TLS ----------
            ctx = ssl.create_default_context()
            t1 = time.time()
            ssock = ctx.wrap_socket(sock, server_hostname=HOST)
            tls = (time.time() - t1) * 1000

            # ---------- HTTP TTFB ----------
            conn = http.client.HTTPSConnection(HOST, timeout=TIMEOUT)
            conn.sock = ssock

            t2 = time.time()
            conn.request("GET", "/cdn-cgi/trace")
            resp = conn.getresponse()
            ttfb = (time.time() - t2) * 1000

            # ---------- 下载测速 ----------
            start_dl = time.time()
            data = resp.read(DOWNLOAD_SIZE)
            duration = time.time() - start_dl

            if duration > 0:
                speed = len(data) / duration / 1024  # KB/s
                speed_list.append(speed)

            tcp_list.append(tcp)
            tls_list.append(tls)
            ttfb_list.append(ttfb)

        except Exception:
            fail += 1
            if fail >= TEST_TIMES:
                return None

    loss = fail / TEST_TIMES
    if loss > MAX_LOSS or not tcp_list:
        return None

    return (
        ip,
        round(sum(tcp_list) / len(tcp_list), 1),
        round(sum(tls_list) / len(tls_list), 1),
        round(sum(ttfb_list) / len(ttfb_list), 1),
        round(sum(speed_list) / len(speed_list), 1) if speed_list else 0,
        round(loss, 2),
    )


# ===== 并发扫描 =====
results = []
start_time = time.time()

with ThreadPoolExecutor(max_workers=THREADS) as pool:
    futures = [pool.submit(test_ip, ip) for ip in ip_list]

    for i, f in enumerate(as_completed(futures), 1):
        r = f.result()

        if r:
            ip, tcp, tls, ttfb, speed, loss = r
            print(
                f"[OK] {ip:15} "
                f"TCP:{tcp:5}ms TLS:{tls:5}ms "
                f"TTFB:{ttfb:5}ms SPD:{speed:7}KB/s "
                f"LOSS:{loss}"
            )
            results.append(r)

        if i % 300 == 0:
            print(f"进度 {i}/{len(ip_list)}")


# ===== 排序（真实优选逻辑）=====
# 优先级：
# 1. 丢包率
# 2. TTFB
# 3. 下载速度（越大越好）
# 4. TLS
# 5. TCP
results.sort(key=lambda x: (x[5], x[3], -x[4], x[2], x[1]))


# ===== 输出最优 =====
print("\n================ 最优 IP ================\n")

for ip, tcp, tls, ttfb, speed, loss in results[:TOP_N]:
    print(
        f"{ip:15} TCP:{tcp:5}ms TLS:{tls:5}ms "
        f"TTFB:{ttfb:5}ms SPD:{speed:7}KB/s LOSS:{loss}"
    )

print("\n=========================================")
print(f"完成，用时 {round(time.time() - start_time, 1)} 秒")
print(f"有效 IP：{len(results)}")
