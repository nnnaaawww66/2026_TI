from maix import app, camera, display, err, image, time, webrtc
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import threading


STREAM_WIDTH = 1280
STREAM_HEIGHT = 720
STREAM_FPS = 30
STREAM_BITRATE = 3_000_000
STREAM_GOP = 15
WEB_HTTP_PORT = 8000
WEB_SIGNALING_PORT = 8001
STUN_SERVER = "stun:stun.miwifi.com:3478"
LOCAL_RECORD_DIR = "/root/maixcam2_recordings"
LOCAL_RECORD_FREE_MARGIN = 100 * 1024 * 1024
RECORDING_WRITE_LOCK = threading.Lock()

WEB_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>图传</title>
    <style>
        html, body {
            margin: 0;
            min-height: 100%;
            background: #3a3a3a;
            color: #fff;
            font-family: Arial, "Microsoft YaHei", sans-serif;
        }
        body {
            display: flex;
            justify-content: center;
            align-items: center;
            box-sizing: border-box;
            padding: 24px;
        }
        #container {
            width: 100%;
            max-width: 1350px;
            text-align: center;
        }
        #title {
            margin-bottom: 30px;
            padding: 16px 20px;
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.09);
            font-size: clamp(24px, 3vw, 42px);
            font-weight: bold;
            box-shadow: 0 8px 28px rgba(0, 0, 0, 0.12);
        }
        #video-wrap {
            position: relative;
            overflow: hidden;
            width: 100%;
            border-radius: 22px;
            background: #111;
            box-shadow: 0 18px 45px rgba(0, 0, 0, 0.42);
        }
        #video {
            display: block;
            width: 100%;
            max-height: 72vh;
            background: #111;
        }
        #resolution-badge, #status {
            position: absolute;
            bottom: 18px;
            padding: 8px 14px;
            border-radius: 12px;
            background: rgba(0, 0, 0, 0.62);
            font-size: 16px;
            backdrop-filter: blur(6px);
        }
        #resolution-badge {
            left: 18px;
        }
        #status {
            right: 18px;
        }
        #record-controls {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            align-items: center;
            gap: 12px;
            margin: -12px 0 24px;
        }
        #record-target, #record-button {
            height: 42px;
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 10px;
            color: #fff;
            font-size: 16px;
        }
        #record-target {
            padding: 0 12px;
            background: #505050;
        }
        #record-button {
            min-width: 132px;
            padding: 0 18px;
            background: #c63737;
            cursor: pointer;
        }
        #record-button:hover:not(:disabled) {
            background: #dc4444;
        }
        #record-button.recording {
            background: #8d2020;
            box-shadow: 0 0 0 4px rgba(220, 68, 68, 0.18);
        }
        #record-button:disabled, #record-target:disabled {
            cursor: not-allowed;
            opacity: 0.55;
        }
        #record-timer {
            min-width: 68px;
            font-family: Consolas, monospace;
            font-size: 18px;
        }
        #record-message {
            flex-basis: 100%;
            min-height: 20px;
            color: #d7d7d7;
            font-size: 14px;
        }
        #fullscreen-btn {
            position: fixed;
            right: 30px;
            bottom: 30px;
            display: none;
            width: 56px;
            height: 56px;
            border: 0;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.18);
            color: #fff;
            font-size: 24px;
            cursor: pointer;
            backdrop-filter: blur(8px);
        }
        @media (max-width: 600px) {
            body {
                padding: 12px;
            }
            #title {
                margin-bottom: 16px;
            }
            #record-controls {
                margin: 0 0 16px;
                gap: 8px;
            }
            #record-target, #record-button {
                height: 38px;
                font-size: 14px;
            }
            #resolution-badge, #status {
                bottom: 10px;
                padding: 6px 10px;
                font-size: 13px;
            }
            #resolution-badge {
                left: 10px;
            }
            #status {
                right: 10px;
            }
        }
    </style>
</head>
<body>
    <main id="container">
        <div id="title">图传</div>
        <div id="record-controls">
            <label for="record-target">保存位置</label>
            <select id="record-target">
                <option value="computer">电脑端</option>
                <option value="maixcam">MaixCam2 本地</option>
            </select>
            <button id="record-button" disabled>● 开始录制</button>
            <span id="record-timer">00:00</span>
            <div id="record-message">连接视频后即可录制</div>
        </div>
        <div id="video-wrap">
            <video id="video" autoplay playsinline muted></video>
            <div id="resolution-badge">
                <span id="resolution">-- × --</span>
                <span style="margin-left: 8px; opacity: 0.85;">H264</span>
            </div>
            <div id="status">正在连接</div>
        </div>
    </main>
    <button id="fullscreen-btn" title="全屏">⛶</button>
    <script>
        const signalingPort = __SIGNALING_PORT__;
        const stunServer = "__STUN_SERVER__";
        const clientId = Math.random().toString(36).slice(2, 12);
        const socketUrl = `ws://${window.location.hostname}:${signalingPort}/${clientId}`;
        const socket = new WebSocket(socketUrl);
        const video = document.getElementById("video");
        const statusBox = document.getElementById("status");
        const resolutionBox = document.getElementById("resolution");
        const fullscreenButton = document.getElementById("fullscreen-btn");
        const recordTarget = document.getElementById("record-target");
        const recordButton = document.getElementById("record-button");
        const recordTimer = document.getElementById("record-timer");
        const recordMessage = document.getElementById("record-message");
        const recordingBitrate = __RECORD_BITRATE__;
        let peer = null;
        let mediaRecorder = null;
        let recordedChunks = [];
        let recordingDestination = "computer";
        let recordingStartedAt = 0;
        let recordingTimerId = null;

        function setStatus(text) {
            statusBox.textContent = text;
        }

        function updateResolution() {
            if (video.videoWidth && video.videoHeight) {
                resolutionBox.textContent = `${video.videoWidth} × ${video.videoHeight}`;
            }
        }

        function timestampName() {
            const now = new Date();
            const pad = (value) => String(value).padStart(2, "0");
            return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_` +
                   `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
        }

        function elapsedText(milliseconds) {
            const seconds = Math.floor(milliseconds / 1000);
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const remainSeconds = seconds % 60;
            const pad = (value) => String(value).padStart(2, "0");
            if (hours > 0) {
                return `${pad(hours)}:${pad(minutes)}:${pad(remainSeconds)}`;
            }
            return `${pad(minutes)}:${pad(remainSeconds)}`;
        }

        function recorderExtension(mimeType) {
            return mimeType && mimeType.toLowerCase().includes("mp4") ? "mp4" : "webm";
        }

        function createRecorder(stream) {
            const candidates = [
                "video/mp4;codecs=avc1.42E01E",
                "video/webm;codecs=vp9",
                "video/webm;codecs=vp8",
                "video/webm"
            ];

            for (const mimeType of candidates) {
                if (MediaRecorder.isTypeSupported &&
                    !MediaRecorder.isTypeSupported(mimeType)) {
                    continue;
                }
                try {
                    return new MediaRecorder(stream, {
                        mimeType,
                        videoBitsPerSecond: recordingBitrate
                    });
                } catch (error) {
                    console.warn(`Recorder format unavailable: ${mimeType}`, error);
                }
            }

            return new MediaRecorder(stream, {
                videoBitsPerSecond: recordingBitrate
            });
        }

        function downloadRecording(blob, filename) {
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 30000);
        }

        async function uploadRecording(blob, extension, timestamp) {
            const response = await fetch("/api/recordings", {
                method: "POST",
                headers: {
                    "Content-Type": blob.type || `video/${extension}`,
                    "X-Recording-Extension": extension,
                    "X-Recording-Timestamp": timestamp
                },
                body: blob
            });
            let result = {};
            try {
                result = await response.json();
            } catch (error) {
                result = {};
            }
            if (!response.ok || !result.ok) {
                throw new Error(result.error || `HTTP ${response.status}`);
            }
            return result;
        }

        function restoreRecordControls() {
            const hasLiveVideo = video.srcObject &&
                video.srcObject.getVideoTracks().some((track) => track.readyState === "live");
            recordButton.disabled =
                !hasLiveVideo || !("MediaRecorder" in window) || mediaRecorder !== null;
            recordButton.classList.remove("recording");
            recordButton.textContent = "● 开始录制";
            recordTarget.disabled = false;
        }

        async function finishRecording() {
            clearInterval(recordingTimerId);
            recordingTimerId = null;
            recordButton.disabled = true;
            recordButton.classList.remove("recording");
            recordButton.textContent = "保存中...";

            const mimeType = mediaRecorder.mimeType ||
                (recordedChunks[0] && recordedChunks[0].type) ||
                "video/webm";
            const extension = recorderExtension(mimeType);
            const timestamp = timestampName();
            const filename = `${timestamp}.${extension}`;
            const blob = new Blob(recordedChunks, { type: mimeType });
            recordedChunks = [];

            if (!blob.size) {
                recordMessage.textContent = "录制失败：没有产生视频数据";
                mediaRecorder = null;
                restoreRecordControls();
                return;
            }

            try {
                if (recordingDestination === "maixcam") {
                    const result = await uploadRecording(blob, extension, timestamp);
                    recordMessage.textContent = `已保存到 MaixCam2：${result.path}`;
                } else {
                    downloadRecording(blob, filename);
                    recordMessage.textContent = `已保存到电脑：${filename}`;
                }
            } catch (error) {
                console.error(error);
                if (recordingDestination === "maixcam") {
                    downloadRecording(blob, filename);
                    recordMessage.textContent =
                        `MaixCam2 保存失败，已转为电脑下载：${error.message}`;
                } else {
                    recordMessage.textContent = `电脑保存失败：${error.message}`;
                }
            } finally {
                mediaRecorder = null;
                restoreRecordControls();
            }
        }

        function startRecording() {
            if (!video.srcObject || !("MediaRecorder" in window)) {
                recordMessage.textContent = "当前浏览器不支持录制或视频尚未连接";
                return;
            }

            try {
                mediaRecorder = createRecorder(video.srcObject);
                recordedChunks = [];
                recordingDestination = recordTarget.value;
                mediaRecorder.ondataavailable = (event) => {
                    if (event.data && event.data.size > 0) {
                        recordedChunks.push(event.data);
                    }
                };
                mediaRecorder.onerror = (event) => {
                    console.error(event.error);
                    recordMessage.textContent = `录制错误：${event.error.message}`;
                };
                mediaRecorder.onstop = finishRecording;
                mediaRecorder.start(1000);

                recordingStartedAt = performance.now();
                recordTimer.textContent = "00:00";
                recordingTimerId = setInterval(() => {
                    recordTimer.textContent =
                        elapsedText(performance.now() - recordingStartedAt);
                }, 500);
                recordTarget.disabled = true;
                recordButton.classList.add("recording");
                recordButton.textContent = "■ 停止录制";
                recordMessage.textContent = recordingDestination === "maixcam"
                    ? "正在录制，停止后保存到 MaixCam2"
                    : "正在录制，停止后下载到电脑";
            } catch (error) {
                console.error(error);
                mediaRecorder = null;
                recordMessage.textContent = `无法开始录制：${error.message}`;
                restoreRecordControls();
            }
        }

        function stopRecording() {
            if (mediaRecorder && mediaRecorder.state === "recording") {
                recordButton.disabled = true;
                recordButton.textContent = "正在停止...";
                mediaRecorder.stop();
            }
        }

        function waitForIceGathering(connection) {
            if (connection.iceGatheringState === "complete") {
                return Promise.resolve();
            }

            return new Promise((resolve) => {
                const checkState = () => {
                    if (connection.iceGatheringState === "complete") {
                        connection.removeEventListener("icegatheringstatechange", checkState);
                        resolve();
                    }
                };
                connection.addEventListener("icegatheringstatechange", checkState);
                setTimeout(() => {
                    connection.removeEventListener("icegatheringstatechange", checkState);
                    resolve();
                }, 3000);
            });
        }

        async function handleOffer(message) {
            if (peer) {
                stopRecording();
                peer.close();
            }

            peer = new RTCPeerConnection({
                bundlePolicy: "max-bundle",
                iceServers: [{ urls: [stunServer] }]
            });

            peer.ontrack = (event) => {
                video.srcObject = event.streams[0];
                video.play();
                fullscreenButton.style.display = "block";
                restoreRecordControls();
                if (!mediaRecorder) {
                    recordMessage.textContent = "可选择保存位置并开始录制";
                }
                setStatus("已连接");
            };
            peer.onconnectionstatechange = () => {
                if (peer.connectionState === "failed" ||
                    peer.connectionState === "disconnected" ||
                    peer.connectionState === "closed") {
                    stopRecording();
                    recordButton.disabled = true;
                    setStatus("连接断开");
                }
            };

            await peer.setRemoteDescription({
                type: message.type,
                sdp: message.sdp
            });
            await peer.setLocalDescription(await peer.createAnswer());
            await waitForIceGathering(peer);

            socket.send(JSON.stringify({
                id: "server",
                type: peer.localDescription.type,
                sdp: peer.localDescription.sdp
            }));
        }

        socket.onopen = () => {
            setStatus("正在获取视频");
            socket.send(JSON.stringify({ id: "server", type: "request" }));
        };
        socket.onmessage = async (event) => {
            if (typeof event.data !== "string") {
                return;
            }
            const message = JSON.parse(event.data);
            if (message.type === "offer") {
                try {
                    await handleOffer(message);
                } catch (error) {
                    console.error(error);
                    setStatus("连接失败");
                }
            }
        };
        socket.onerror = () => setStatus("信令连接失败");
        socket.onclose = () => {
            if (!peer || peer.connectionState !== "connected") {
                setStatus("信令已断开");
            }
        };

        video.addEventListener("loadedmetadata", updateResolution);
        video.addEventListener("resize", updateResolution);
        recordButton.onclick = () => {
            if (mediaRecorder && mediaRecorder.state === "recording") {
                stopRecording();
            } else if (!mediaRecorder) {
                startRecording();
            }
        };
        window.addEventListener("beforeunload", (event) => {
            if (mediaRecorder && mediaRecorder.state === "recording") {
                event.preventDefault();
                event.returnValue = "";
            }
        });
        fullscreenButton.onclick = () => {
            if (!document.fullscreenElement) {
                video.requestFullscreen?.();
            } else {
                document.exitFullscreen?.();
            }
        };
    </script>
</body>
</html>
"""

WEB_PAGE_BYTES = (
    WEB_PAGE.replace("__SIGNALING_PORT__", str(WEB_SIGNALING_PORT))
    .replace("__STUN_SERVER__", STUN_SERVER)
    .replace("__RECORD_BITRATE__", str(STREAM_BITRATE))
    .encode("utf-8")
)


class WebPageHandler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(WEB_PAGE_BYTES)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(WEB_PAGE_BYTES)
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/recordings":
            self.send_json(404, {"ok": False, "error": "接口不存在"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0:
            self.send_json(400, {"ok": False, "error": "录像数据为空"})
            return

        extension = self.headers.get("X-Recording-Extension", "webm").lower()
        if extension not in ("mp4", "webm"):
            self.send_json(400, {"ok": False, "error": "不支持的录像格式"})
            return

        temporary_path = None
        try:
            os.makedirs(LOCAL_RECORD_DIR, exist_ok=True)
            free_bytes = shutil.disk_usage(LOCAL_RECORD_DIR).free
            if content_length + LOCAL_RECORD_FREE_MARGIN > free_bytes:
                self.send_json(
                    507,
                    {
                        "ok": False,
                        "error": "MaixCam2 存储空间不足，请清理录像后重试",
                    },
                )
                return

            with RECORDING_WRITE_LOCK:
                requested_timestamp = self.headers.get(
                    "X-Recording-Timestamp",
                    "",
                )
                timestamp_is_valid = (
                    len(requested_timestamp) == 15
                    and requested_timestamp[8] == "_"
                    and requested_timestamp[:8].isdigit()
                    and requested_timestamp[9:].isdigit()
                )
                timestamp = (
                    requested_timestamp
                    if timestamp_is_valid
                    else datetime.now().strftime("%Y%m%d_%H%M%S")
                )
                filename = f"{timestamp}.{extension}"
                final_path = os.path.join(LOCAL_RECORD_DIR, filename)
                sequence = 1
                while os.path.exists(final_path):
                    filename = f"{timestamp}_{sequence:02d}.{extension}"
                    final_path = os.path.join(LOCAL_RECORD_DIR, filename)
                    sequence += 1

                temporary_path = f"{final_path}.part"
                remaining = content_length
                with open(temporary_path, "wb") as recording_file:
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ConnectionError("录像上传中断")
                        recording_file.write(chunk)
                        remaining -= len(chunk)
                    recording_file.flush()
                    os.fsync(recording_file.fileno())

                os.replace(temporary_path, final_path)
                temporary_path = None

            print(f"Recording saved: {final_path} ({content_length} bytes)")
            self.send_json(
                200,
                {
                    "ok": True,
                    "filename": filename,
                    "path": final_path,
                    "size": content_length,
                },
            )
        except Exception as exc:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass
            print(f"Failed to save recording: {exc}")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def log_message(self, format, *args):
        return


class WebPageServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_web_page_server():
    server = WebPageServer(("", WEB_HTTP_PORT), WebPageHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="maixcam2-web-page",
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        server.server_close()
        raise
    return server, thread


def stop_web_page_server(server, thread):
    if server is None:
        return

    try:
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2)
    except Exception as exc:
        print(f"Warning: failed to stop web page server: {exc}")


def close_resource(name, resource):
    """Close a Maix resource without hiding an earlier runtime error."""
    if resource is None:
        return

    try:
        result = resource.close()
        # Camera.close() returns None; Display.close() returns an Err code.
        if result is not None and result != err.Err.ERR_NONE:
            print(f"Warning: failed to close {name}: {err.to_str(result)}")
    except Exception as exc:
        print(f"Warning: failed to close {name}: {exc}")


disp = None
stream_cam = None
preview_cam = None
web_server = None
web_server_started = False
page_server = None
page_thread = None

try:
    disp = display.Display()

    # The WebRTC hardware encoder requires an NV21 (YVU420SP) camera channel.
    stream_cam = camera.Camera(
        STREAM_WIDTH,
        STREAM_HEIGHT,
        image.Format.FMT_YVU420SP,
        fps=STREAM_FPS,
    )

    # Keep the local preview independent from the channel owned by WebRTC.
    preview_cam = stream_cam.add_channel(
        disp.width(),
        disp.height(),
        image.Format.FMT_RGB888,
        fps=STREAM_FPS,
    )

    web_server = webrtc.WebRTC(
        port=WEB_HTTP_PORT,
        stream_type=webrtc.WebRTCStreamType.WEBRTC_STREAM_H264,
        rc_type=webrtc.WebRTCRCType.WEBRTC_RC_CBR,
        bitrate=STREAM_BITRATE,
        gop=STREAM_GOP,
        signaling_port=WEB_SIGNALING_PORT,
        stun_server=STUN_SERVER,
        http_server=False,
    )
    err.check_raise(
        web_server.bind_camera(stream_cam),
        "Failed to bind the camera to the WebRTC server",
    )
    err.check_raise(web_server.start(), "Failed to start the WebRTC server")
    web_server_started = True
    page_server, page_thread = start_web_page_server()

    urls = web_server.get_urls()
    print("WebRTC stream started.")
    if urls:
        print("Open one of these URLs with the latest Chrome or Edge:")
        for url in urls:
            print(f"  {url}")
    else:
        print(f"Open http://<MaixCam2-IP>:{WEB_HTTP_PORT} with Chrome or Edge.")

    report_start_ms = time.ticks_ms()
    report_frames = 0
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 30

    while not app.need_exit():
        try:
            img = preview_cam.read()
            if img is None:
                raise RuntimeError("camera read returned None")
            disp.show(img)
            report_frames += 1
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            print(f"Warning: camera frame dropped (consecutive={consecutive_errors}): {exc}")
            if consecutive_errors > MAX_CONSECUTIVE_ERRORS:
                print("Warning: too many consecutive camera errors, resetting counter to avoid log spam")
                consecutive_errors = 0
            time.sleep_ms(1)

        now_ms = time.ticks_ms()
        elapsed_ms = now_ms - report_start_ms
        if elapsed_ms >= 1000:
            fps = report_frames * 1000.0 / elapsed_ms
            print(f"Local preview: {fps:.2f} fps")
            report_start_ms = now_ms
            report_frames = 0
finally:
    stop_web_page_server(page_server, page_thread)

    if web_server_started:
        try:
            result = web_server.stop()
            if result != err.Err.ERR_NONE:
                print(f"Warning: failed to stop WebRTC server: {err.to_str(result)}")
        except Exception as exc:
            print(f"Warning: failed to stop WebRTC server: {exc}")

    # Release the server before closing either camera channel.
    web_server = None
    close_resource("preview camera", preview_cam)
    close_resource("stream camera", stream_cam)
    close_resource("display", disp)
