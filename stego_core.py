# -*- coding: utf-8 -*-
"""
音频频谱隐写核心算法模块
将文字图像通过 IFFT + 重叠相加编码进音频的超声波频段
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import signal
import soundfile as sf

TARGET_SR = 192000          # 目标采样率
N_FFT = 4096                # FFT 点数（192kHz 下频率分辨率约 46.9Hz/bin）
HOP = N_FFT // 4            # 步长，保证 75% 重叠

# Windows 常见中文字体，按优先级尝试
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
    r"C:\Windows\Fonts\arial.ttf",
]


def load_audio(path, target_sr=TARGET_SR):
    """
    读取音频文件（WAV/FLAC/OGG/MP3），统一重采样到 target_sr。
    返回 (data[N, C] float32, target_sr, 原始采样率)
    """
    data, sr = sf.read(path, always_2d=True, dtype="float32")
    orig_sr = sr
    if sr != target_sr:
        g = math.gcd(int(sr), target_sr)
        data = signal.resample_poly(data, target_sr // g, sr // g, axis=0)
        data = data.astype(np.float32)
    return data, target_sr, orig_sr


def _load_font(font_size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, font_size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def render_text_image(text, font_size=64, color="white"):
    """
    将文字渲染为黑底图像，返回 HxW 的 uint8 数组（取红色通道值）。
    白色/红色文字的 R 通道均为 255，因此编码时只取 R 通道。
    """
    font = _load_font(font_size)
    # 先测量文字尺寸
    tmp = Image.new("L", (8, 8), 0)
    d = ImageDraw.Draw(tmp)
    bbox = d.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    pad = max(8, font_size // 8)
    img = Image.new("L", (w + pad * 2, h + pad * 2), 0)
    d = ImageDraw.Draw(img)
    fill = 255  # 灰度值即红色通道值
    d.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=fill)
    return np.asarray(img, dtype=np.uint8)


def synthesize_ultrasound(img, sr, f_low, f_high, duration, progress_cb=None):
    """
    把图像（HxW uint8，R 通道）编码为超声波时域信号。
    顶部=高频，底部=低频。返回 float32 单声道数组，峰值归一化到 0.95。
    """
    total = int(sr * duration)
    n_bins = N_FFT // 2 + 1
    bin_low = int(np.floor(f_low / sr * N_FFT))
    bin_high = int(np.ceil(f_high / sr * N_FFT))
    bin_high = min(bin_high, n_bins - 1)
    n_rows = bin_high - bin_low
    if n_rows < 2:
        raise ValueError("频率范围太窄，无法绘制图像")
    width = max(8, total // HOP)

    # 图像缩放到 (width, n_rows)，使每一行精确对应一个频点
    pil = Image.fromarray(img).resize((width, n_rows), Image.BILINEAR)
    amp = np.asarray(pil, dtype=np.float32).T / 255.0  # -> (width, n_rows)

    # 频率映射：行 -> bin（顶部=高频）
    rows = np.arange(n_rows)
    ratio = 1.0 - rows / (n_rows - 1)
    bins = bin_low + (ratio * (bin_high - bin_low - 1)).astype(np.int64)

    # 伪随机相位，避免各列同相叠加产生啸叫
    cols = np.arange(width)
    phases = (cols[:, None] * 0.7 + rows[None, :] * 0.3) % (2 * np.pi)

    if progress_cb:
        progress_cb(20, "构建频谱矩阵...")

    # 批量构建单边复数频谱 (width, n_bins)
    spectra = np.zeros((width, n_bins), dtype=np.complex64)
    spectra[cols[:, None], bins[None, :]] = amp * np.exp(1j * phases).astype(np.complex64)

    if progress_cb:
        progress_cb(40, "IFFT 合成时域帧...")

    frames = np.fft.irfft(spectra, n=N_FFT, axis=1).astype(np.float32)  # (width, N_FFT)
    frames *= signal.windows.hann(N_FFT, sym=False).astype(np.float32)

    if progress_cb:
        progress_cb(70, "重叠相加...")

    # Overlap-Add
    out_len = (width - 1) * HOP + N_FFT
    out = np.zeros(out_len, dtype=np.float32)
    for i in range(width):
        s = i * HOP
        out[s:s + N_FFT] += frames[i]

    if progress_cb:
        progress_cb(90, "归一化...")

    peak = np.max(np.abs(out))
    if peak > 1e-9:
        out *= 0.95 / peak

    # 对齐到请求时长
    if len(out) >= total:
        out = out[:total]
    else:
        out = np.pad(out, (0, total - len(out)))

    if progress_cb:
        progress_cb(100, "完成")
    return out


def mix_audio(music, hidden, start_sample, gain_db):
    """
    将隐藏音频按增益混入音乐。music: (N, C)，hidden: (M,) 单声道。
    返回混音后的新数组（峰值归一化到 0.99 防削波）。
    """
    mixed = music.copy()
    n_ch = music.shape[1]
    g = 10.0 ** (gain_db / 20.0)
    hid = hidden * g

    end = min(start_sample + len(hid), music.shape[0])
    seg_len = end - start_sample
    if seg_len <= 0:
        raise ValueError("绘制区域超出音频范围")
    for c in range(n_ch):
        mixed[start_sample:end, c] += hid[:seg_len]

    peak = np.max(np.abs(mixed))
    if peak > 0.99:
        mixed *= 0.99 / peak
    return mixed


def export_audio(path, data, sr, fmt):
    """导出 24-bit WAV 或 FLAC"""
    fmt = fmt.upper()
    if fmt == "WAV":
        sf.write(path, data, sr, subtype="PCM_24", format="WAV")
    elif fmt == "FLAC":
        sf.write(path, data, sr, subtype="PCM_24", format="FLAC")
    else:
        raise ValueError("不支持的格式: " + fmt)


def compute_spectrogram(mono, sr, nperseg=4096, f_min=0, f_max=None):
    """
    计算 STFT 频谱用于显示。
    返回 (t, f_khz, Sxx_db)，已按频率范围裁剪。
    """
    noverlap = nperseg * 3 // 4
    f, t, Z = signal.stft(mono, fs=sr, window="hann",
                          nperseg=nperseg, noverlap=noverlap)
    S = 20 * np.log10(np.abs(Z) + 1e-10)
    if f_max is None:
        f_max = sr / 2
    mask = (f >= f_min) & (f <= f_max)
    return t, f[mask] / 1000.0, S[mask]
