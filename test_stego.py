# -*- coding: utf-8 -*-
"""无界面自测：生成测试音乐 -> 嵌入文字 -> 导出 -> 验证区域能量"""
import numpy as np
import stego_core as core

sr = core.TARGET_SR
dur = 8.0
t = np.arange(int(sr * dur)) / sr

# 生成双声道测试音乐（和弦 + 扫频），峰值 0.5
music = np.stack([
    0.25 * np.sin(2 * np.pi * 220 * t) + 0.15 * np.sin(2 * np.pi * 440 * t),
    0.25 * np.sin(2 * np.pi * 330 * t) + 0.15 * np.sin(2 * np.pi * 550 * t),
], axis=1).astype(np.float32)
core.export_audio(r"e:\新建文件夹 (3)\test_music.wav", music, sr, "WAV")
print("测试音乐已生成")

# 加载 -> 渲染文字 -> 嵌入区域: 2-6s, 25-45kHz
data, sr, orig = core.load_audio(r"e:\新建文件夹 (3)\test_music.wav")
img = core.render_text_image("HELLO 你好", font_size=96)
print("文字图像尺寸:", img.shape)

hidden = core.synthesize_ultrasound(img, sr, 25000, 45000, 4.0)
print("隐藏信号: len=%d peak=%.3f" % (len(hidden), np.max(np.abs(hidden))))

mixed = core.mix_audio(data, hidden, int(2.0 * sr), -40)
core.export_audio(r"e:\新建文件夹 (3)\test_out.wav", mixed, sr, "WAV")
core.export_audio(r"e:\新建文件夹 (3)\test_out.flac", mixed, sr, "FLAC")
print("已导出 test_out.wav / test_out.flac")

# 验证：区域内 25-45kHz 能量应显著高于区域外
tt, ff, S = core.compute_spectrogram(mixed.mean(axis=1), sr)
fmask = (ff >= 25) & (ff <= 45)
in_t = (tt >= 2.5) & (tt <= 5.5)
out_t = (tt >= 0.2) & (tt <= 1.5)
e_in = S[np.ix_(fmask, in_t)].mean()
e_out = S[np.ix_(fmask, out_t)].mean()
print("区域内能量 %.1f dB, 区域外能量 %.1f dB, 对比度 %.1f dB"
      % (e_in, e_out, e_in - e_out))
assert e_in - e_out > 20, "嵌入验证失败"
print("✔ 嵌入验证通过")

# 验证导出文件参数
import soundfile as sf
for p in ["test_out.wav", "test_out.flac"]:
    info = sf.info(r"e:\新建文件夹 (3)\\" + p)
    print(p, "->", info.samplerate, "Hz,", info.channels, "ch,",
          info.subtype, info.format)
