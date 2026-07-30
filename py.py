import socket
import struct
import cv2
import numpy as np
import time
import os
from datetime import datetime

class StreamRecorder:
    def __init__(self):
        self.sock = None
        self.recording = True  # 默认开始录制
        self.video_writer = None
        self.fps = 20
        self.frame_width = 640
        self.frame_height = 320
        self.frame_count = 0
        self.recorded_frames = 0
        self.current_filename = None
        self.max_frames_per_file = 3600  # 每个文件最多3600帧（约3分钟）
        self.file_count = 0
        
    def get_filename(self):
        """生成文件名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.file_count += 1
        return f"recordings/recording_{timestamp}_{self.file_count}.mp4"
    
    def create_video_writer(self):
        """创建视频写入器"""
        # 确保recordings目录存在
        if not os.path.exists('recordings'):
            os.makedirs('recordings')
        
        self.current_filename = self.get_filename()
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter(
            self.current_filename, 
            fourcc, 
            self.fps, 
            (self.frame_width, self.frame_height)
        )
        self.recorded_frames = 0
        print(f"📹 录制开始: {self.current_filename}")
    
    def start_server(self):
        """启动UDP服务器"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(0.5)
        self.sock.bind(('0.0.0.0', 8080))
        print("📡 等待接收数据...")
        print("按 'q' 退出")
        
        # 初始化录制
        self.create_video_writer()
    
    def process_frame(self, img):
        """处理帧"""
        if img is None:
            return
        
        self.frame_count += 1
        
        # 录制
        if self.recording and self.video_writer:
            try:
                self.video_writer.write(img)
                self.recorded_frames += 1
            except:
                pass
        
        # 自动分割文件
        if self.recorded_frames >= self.max_frames_per_file:
            self.video_writer.release()
            self.create_video_writer()
    
    def receive_and_record(self):
        """接收并录制"""
        self.start_server()
        
        buffer = bytearray()
        expected_len = 0
        receiving = False
        
        # 预分配窗口
        try:
            cv2.namedWindow('Stream', cv2.WINDOW_NORMAL)
            cv2.resizeWindow('Stream', 640, 320)
        except:
            pass
        
        while True:
            try:
                # 接收数据
                try:
                    data, addr = self.sock.recvfrom(65535)
                except socket.timeout:
                    cv2.waitKey(10)
                    continue
                except Exception as e:
                    cv2.waitKey(10)
                    continue
                
                if len(data) < 8:
                    continue
                
                # 检查帧头
                if not receiving:
                    magic = struct.unpack('>I', data[:4])[0]
                    if magic == 0xABCD1234:
                        expected_len = struct.unpack('>I', data[4:8])[0]
                        if 100 < expected_len < 1024*1024:
                            buffer = bytearray()
                            receiving = True
                        continue
                
                # 接收帧数据
                if receiving:
                    buffer.extend(data)
                    if len(buffer) >= expected_len:
                        try:
                            jpeg_data = bytes(buffer[:expected_len])
                            
                            # 解码
                            img = cv2.imdecode(
                                np.frombuffer(jpeg_data, dtype=np.uint8), 
                                cv2.IMREAD_COLOR
                            )
                            
                            if img is not None and img.size > 0:
                                # 处理帧
                                self.process_frame(img)
                                
                                # 显示状态
                                cv2.putText(img, f"REC {self.recorded_frames}", (10, 30),
                                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                                cv2.putText(img, f"Frames: {self.frame_count}", (10, 60),
                                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                                
                                cv2.imshow('Stream', img)
                            else:
                                # 解码失败，跳过
                                pass
                                
                        except Exception as e:
                            # 解码错误，跳过
                            pass
                        
                        receiving = False
                        buffer = bytearray()
                
                # 处理按键
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('s'):
                    # 手动分割文件
                    if self.recording:
                        self.video_writer.release()
                        self.create_video_writer()
                        print("📂 手动分割文件")
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                # 忽略错误，继续运行
                time.sleep(0.1)
                continue
        
        # 清理
        self.cleanup()
    
    def cleanup(self):
        """清理资源"""
        if self.video_writer:
            self.video_writer.release()
            print(f"📹 录制结束: {self.current_filename} ({self.recorded_frames} 帧)")
        
        if self.sock:
            self.sock.close()
        
        try:
            cv2.destroyAllWindows()
        except:
            pass
        
        print(f"✅ 程序结束，共接收 {self.frame_count} 帧")

if __name__ == "__main__":
    recorder = StreamRecorder()
    recorder.receive_and_record()