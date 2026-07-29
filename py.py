import socket
import struct
import cv2
import numpy as np

def receive_stream():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', 8080))
    sock.settimeout(0.1)
    
    print("等待接收数据...")
    
    buffer = {}
    current_frame = None
    expected_len = 0
    
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            
            if len(data) >= 8:
                magic = struct.unpack('>I', data[:4])[0]
                if magic == 0xABCD1234:
                    # 新帧开始
                    expected_len = struct.unpack('>I', data[4:8])[0]
                    current_frame = bytearray()
                    continue
            
            # 接收数据块
            if current_frame is not None:
                current_frame.extend(data)
                if len(current_frame) >= expected_len:
                    # 完整帧接收完成
                    jpeg_data = bytes(current_frame[:expected_len])
                    
                    # 解码显示
                    img = cv2.imdecode(np.frombuffer(jpeg_data, dtype=np.uint8), 
                                      cv2.IMREAD_COLOR)
                    if img is not None:
                        cv2.imshow('Stream', img)
                        cv2.waitKey(1)
                    
                    current_frame = None
                    
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            break
    
    sock.close()

if __name__ == "__main__":
    receive_stream()