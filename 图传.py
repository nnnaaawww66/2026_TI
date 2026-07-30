from maix import app, camera, image, time, webrtc, network, err

print("=" * 60)
print("MaixCAM Pro 图传 (高码率)")
print("=" * 60)

print("\n[1] 创建 WiFi 热点...")
wifi = network.wifi.Wifi()
SSID = "MaixCAM_Pro"
PASSWORD = "12345678"

try:
    err_code = wifi.start_ap(
        ssid=SSID,
        password=PASSWORD,
        mode='g',
        channel=6,
        ip='192.168.66.1',
        netmask='255.255.255.0'
    )
    err.check_raise(err_code, "创建热点失败")
    print("  OK 热点: MaixCAM_Pro / 12345678")
except Exception as e:
    print(f"  X 热点失败: {e}")
    app.need_exit()

print("\n[2] 初始化摄像头...")
# GC4653 原生分辨率 2560x1440
cam = camera.Camera(1920, 1024, image.Format.FMT_YVU420SP)
print("  OK 摄像头就绪 (2560x1440)")

print("\n[3] 启动 WebRTC (高码率)...")
# 提高码率到 12Mbps，减少压缩
server = webrtc.WebRTC(
    bitrate=6_000_000,  # 12Mbps
    gop=30,              # 关键帧间隔
    stream_type=webrtc.WebRTCStreamType.WEBRTC_STREAM_H264,
    rc_type=webrtc.WebRTCRCType.WEBRTC_RC_VBR,  # 可变码率，画质更好
)
server.bind_camera(cam)
server.start()
print("  OK WebRTC 启动成功 (码率: 12Mbps)")

urls = server.get_urls()
print("\n" + "=" * 60)
print("服务已启动!")
print(f"WiFi: {SSID} / {PASSWORD}")
for url in urls:
    print(f"访问: {url}")
print("=" * 60)

while not app.need_exit():
    time.sleep(1)

cam.close()