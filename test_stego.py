# -*- coding: utf-8 -*-
"""无界面自测：v1.1 新功能（文字原生渲染 + 图片嵌入）"""
import numpy as np
import stego_core as core

sr = core.TARGET_SR
dur = 8.0
t = np.arange(int(sr * dur)) / sr

music = np.stack([
    0.25 * np.sin(2 * np.pi * 220 * t) + 0.15 * np.sin(2 * np.pi * 440 * t),
    0.25 * np.sin(2 * np.pi * 330 * t) + 0.15 * np.sin(2 * np.pi * 550 * t),
], axis=1).astype(np.float32)
core.export_audio(r"e:\新建文件夹 (3)\test_music.wav", music, sr, "WAV")
data, sr, _ = core.load_audio(r"e:\新建文件夹 (3)\test_music.wav")

# --- ① 文字原生分辨率渲染 ---
w, h = core.region_geometry(sr, 25000, 45000, 4.0)
print("区域像素网格:", w, "x", h)
img_text = core.render_text_fit("HELLO 你好", w, h)
assert img_text.shape == (h, w), "文字渲染尺寸不匹配"
print("文字原生渲染 OK:", img_text.shape)

hidden = core.synthesize_ultrasound(img_text, sr, 25000, 45000, 4.0)
mixed = core.mix_audio(data, hidden, int(2.0 * sr), -40)
core.export_audio(r"e:\新建文件夹 (3)\test_out.wav", mixed, sr, "WAV")

tt, ff, S = core.compute_spectrogram(mixed.mean(axis=1), sr)
fmask = (ff >= 25) & (ff <= 45)
in_t = (tt >= 2.5) & (tt <= 5.5)
out_t = (tt >= 0.2) & (tt <= 1.5)
contrast = S[np.ix_(fmask, in_t)].mean() - S[np.ix_(fmask, out_t)].mean()
print("文字嵌入对比度: %.1f dB" % contrast)
assert contrast > 20

# --- ③ 图片嵌入（用章鱼哥 icon 当 Logo）---
img_logo = core.load_stego_image(
    r"e:\新建文件夹 (3)\icon\icon.png", w, h, mode="fit")
assert img_logo.shape == (h, w)
print("图片加载 OK:", img_logo.shape, "非零像素占比: %.0f%%" %
      (100 * np.mean(img_logo > 10)))

hidden2 = core.synthesize_ultrasound(img_logo, sr, 25000, 45000, 4.0)
mixed2 = core.mix_audio(data, hidden2, int(2.0 * sr), -40)
core.export_audio(r"e:\新建文件夹 (3)\test_out_img.flac", mixed2, sr, "FLAC")
print("✔ 全部测试通过")

# 生成可视化频谱供人工检查
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, axes = plt.subplots(1, 2, figsize=(16, 5))
for ax, (d, title) in zip(axes, [(mixed, "text"), (mixed2, "image")]):
    tt, ff, S = core.compute_spectrogram(d.mean(axis=1), sr)
    m = (ff >= 18) & (ff <= 50)
    Sm = S[m]
    ax.imshow(Sm, origin="lower", aspect="auto", cmap="hot",
              extent=[tt[0], tt[-1], ff[m][0], ff[m][-1]],
              vmin=np.percentile(Sm, 60), vmax=np.percentile(Sm, 99.9))
    ax.set_title(title)
plt.tight_layout()
plt.savefig(r"e:\新建文件夹 (3)\verify_spec_v11.png", dpi=100)
print("验证图已保存 verify_spec_v11.png")
