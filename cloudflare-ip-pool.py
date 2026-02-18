import requests
import ipaddress
import os


def get_cloudflare_ips(network = None):
    url = 'https://api.cloudflare.com/client/v4/ips'
    params = {}

    if network:
        params['networks'] = network

    try:
        response = requests.get(url,params = params)
        print(response.status_code)
        response.raise_for_status()
        data = response.json()
        if data.get('success'):
           result = data.get('result')
           return{
               'etag' : result.get('etag'),
               'ipv4_cidrs' : result.get('ipv4_cidrs'),
               'ipv6_cidrs' : result.get('ipv6_cidrs')
           }
        else:
            print('API请求失败:',data.get('errors',[]))
            print('API请求失败:',data.get('messages',[]))
            return None

    except requests.exceptions.RequestException as e:
        print('请求出错:',e)
        return None

cf_ips = get_cloudflare_ips()
if cf_ips:
    print('etag:',cf_ips['etag'])
    print(f'获取到{len(cf_ips['ipv4_cidrs'])}个IPv4 CIDR段,{len(cf_ips['ipv6_cidrs'])}个IPv6 CIDR段')
else:
    print('API请求失败,程序退出')
    exit(1)

while True:
    SAVE_PATH = input('\n请输入文件保存路径(如D:\\xxx.txt): ').strip()
    if not SAVE_PATH:
        print('路径不能为空,请重新输入!')
        continue
    save_dir = os.path.dirname(SAVE_PATH)
    if save_dir and not os.path.exists(save_dir):
        try:
            os.makedirs(f'{save_dir}')
            print(f'自动创建目录:{save_dir}')
        except Exception as e:
            print(f'自动创建目录失败:{e},请重新输入路径!')
            continue
    break

try:
    with open(SAVE_PATH,'w',encoding='utf-8',newline='') as file:
        file.write('IP地址\n')
        ipv4_count = 0
        print('开始写入ipv4地址...')
        for cidr in cf_ips['ipv4_cidrs']:
            try:
                network = ipaddress.ip_network(cidr,strict=False)
                for ip in network.hosts():
                    file.write(f'{str(ip)}\n')
                    ipv4_count += 1

                    if ipv4_count % 500 == 0:
                        print(f'已经写入{ipv4_count}个IPv4地址...')
            except ValueError as e:
                print(f'跳过无效CIDR:{e}')

        ipv6_count = 0
        print('开始写入ipv6地址...')
        for cidr in cf_ips['ipv6_cidrs']:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
                for ip in network.hosts():
                    file.write(f'{str(ip)}\n')
                    ipv6_count += 1

                    if ipv6_count % 500 == 0:
                        print(f'已经写入{ipv6_count}个IPv6地址...')
                        break

                if ipv6_count >= 1000:
                    break
            except ValueError as e:
                print(f'跳过无效CIDR:{e}')


    print(f'\n文件已成功保存到:{SAVE_PATH}')
    print(f'写入统计:IPv4地址{ipv4_count}个 | IPv6地址{ipv6_count}个')
except Exception as e:
    print(f'写入文件失败:{e}')