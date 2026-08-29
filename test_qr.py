# -*- coding: utf-8 -*-
"""二维码嵌入端到端测试：生成QR -> 嵌入 -> 频谱渲染 -> OpenCV 扫码验证"""
import numpy as np
import qrcode
import cv2
import stego_core as core

sr = core.TARGET_SR
dur = 8.0
t = np.arange(int(sr * dur)) / sr

# 生成测试音乐
music = np.stack([
    0.25 * np.sin(2 * np.pi * 220 * t),
    0.25 * np.sin(2 * np.pi * 330 * t),
], axis=1).astype(np.float32)

# 生成测试二维码
PAYLOAD = "https://github.com/Zhou1019-1/Invincible-Squidward-Presents-Spectrum-Painter"
qr = qrcode.make(PAYLOAD).convert("L")
qr_path = r"e:\新建文件夹 (3)\test_qr.png"
qr.save(qr_path)
print("QR 原始尺寸:", qr.size)

# 嵌入：2-7s, 25-55kHz（接近正方形的像素网格）
w, h = core.region_geometry(sr, 25000, 55000, 5.0)
print("区域像素网格:", w, "x", h)
img = core.load_qr_image(qr_path, w, h)
print("QR 二值化后非零像素占比: %.0f%%" % (100 * np.mean(img > 127)))

hidden = core.synthesize_ultrasound(img, sr, 25000, 55000, 5.0)
mixed = core.mix_audio(music, hidden, int(2.0 * sr), -35)
core.export_audio(r"e:\新建文件夹 (3)\test_qr_out.flac", mixed, sr, "FLAC")

# 频谱渲染（模拟 Spek 视角），裁剪到嵌入区域
tt, ff, S = core.compute_spectrogram(mixed.mean(axis=1), sr)
fmask = (ff >= 24) & (ff <= 56)
tmask = (tt >= 1.8) & (tt <= 7.2)
Sc = S[np.ix_(fmask, tmask)]
vmin, vmax = np.percentile(Sc, 50), np.percentile(Sc, 99.8)
norm = np.clip((Sc - vmin) / (vmax - vmin + 1e-9), 0, 1)
spec_img = (norm * 255).astype(np.uint8)
spec_img = cv2.resize(spec_img[::-1], None, fx=2, fy=2,
                      interpolation=cv2.INTER_NEAREST)
with open(r"e:\新建文件夹 (3)\verify_qr_spec.png", "wb") as f:
    f.write(cv2.imencode(".png", spec_img)[1].tobytes())

# OpenCV 扫码验证（亮底暗码，频谱截图直接可扫；先 Otsu 二值化提高识别率）
det = cv2.QRCodeDetector()
data, pts, _ = det.detectAndDecode(spec_img)
if not data:
    _, bw = cv2.threshold(spec_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    data, pts, _ = det.detectAndDecode(bw)
    if data:
        print("（二值化后扫出）")
if not data:  # 容错：某些扫码器喜欢暗底亮码，反转再试
    data, pts, _ = det.detectAndDecode(255 - spec_img)
    if data:
        print("（反色后扫出）")
print("扫码结果:", repr(data))
if data == PAYLOAD:
    print("✔✔✔ 频谱中的二维码可以直接扫出！")
elif data:
    print("⚠ 扫出了但内容不一致")
else:
    print("✘ 未能识别")
