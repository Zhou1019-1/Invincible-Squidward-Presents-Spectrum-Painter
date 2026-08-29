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


def region_geometry(sr, f_low, f_high, duration):
    """计算绘制区域对应的像素网格：(width 列数, n_rows 频率行数)"""
    total = int(sr * duration)
    n_bins = N_FFT // 2 + 1
    bin_low = int(np.floor(f_low / sr * N_FFT))
    bin_high = min(int(np.ceil(f_high / sr * N_FFT)), n_bins - 1)
    n_rows = bin_high - bin_low
    width = max(8, total // HOP)
    return width, n_rows


def render_text_fit(text, target_w, target_h, color="white"):
    """
    按目标像素尺寸渲染文字：字号自动适配高度，再整体拉伸填满区域
    （网格线性映射到 时间×频率 显示，所见即所得）。
    """
    pad = 2
    # 二分查找：高度方向能放下的最大字号
    lo, hi = 8, max(16, target_h * 2)
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(mid)
        d = ImageDraw.Draw(Image.new("L", (8, 8), 0))
        bbox = d.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if h <= target_h - pad * 2:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    font = _load_font(best)
    d = ImageDraw.Draw(Image.new("L", (8, 8), 0))
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tmp = Image.new("L", (w, h), 0)
    ImageDraw.Draw(tmp).text((-bbox[0], -bbox[1]), text, font=font, fill=255)
    # 拉伸填满目标网格（LANCZOS 平滑）
    img = tmp.resize((target_w, target_h), Image.LANCZOS)
    return np.asarray(img, dtype=np.uint8)


def load_stego_image(path, target_w, target_h, invert=False):
    """
    加载图片/Logo，拉伸填满目标像素网格（所见即所得：框什么形状就得什么形状）。
    invert: 反色（适合深色 Logo）
    取红色通道；透明 PNG 合成到黑底。
    """
    img = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
    img = Image.alpha_composite(bg, img).convert("RGB")
    r = img.split()[0]  # 红色通道
    r = r.resize((target_w, target_h), Image.BILINEAR)
    arr = np.asarray(r, dtype=np.uint8)
    if invert:
        arr = 255 - arr
    return arr


def _otsu_threshold(arr):
    """Otsu 大津法自动二值化阈值"""
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    prob = hist / arr.size
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * np.arange(256))
    mu_t = mu[-1]
    sigma2 = (mu_t * omega - mu) ** 2 / (omega * (1 - omega) + 1e-12)
    return int(np.argmax(sigma2))


def load_qr_image(path, target_w, target_h):
    """
    二维码专用管线：白底合成 -> 灰度 -> Otsu 二值化 -> 亮底暗码
    -> NEAREST 拉伸填满目标网格（保持硬边缘，平滑插值会糊掉码点）。
    """
    img = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    gray = Image.alpha_composite(bg, img).convert("L")
    arr = np.asarray(gray)
    t = _otsu_threshold(arr)
    # 亮底暗码（不反色）：频谱中显示为亮块+暗码点
    # 超声波频段不可闻，亮底不会产生可闻噪声
    binary = ((arr > t).astype(np.uint8)) * 255
    pil = Image.fromarray(binary).resize((target_w, target_h), Image.NEAREST)
    return np.asarray(pil, dtype=np.uint8)


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


def synthesize_ultrasound(img, sr, f_low, f_high, duration, progress_cb=None,
                          freq_jitter=0.0):
    """
    把图像（HxW uint8，R 通道）编码为超声波时域信号。
    顶部=高频，底部=低频。返回 float32 单声道数组，峰值归一化到 0.95。
    """
    total = int(sr * duration)
    width, n_rows = region_geometry(sr, f_low, f_high, duration)
    n_bins = N_FFT // 2 + 1
    bin_low = int(np.floor(f_low / sr * N_FFT))
    bin_high = min(int(np.ceil(f_high / sr * N_FFT)), n_bins - 1)
    if n_rows < 2:
        raise ValueError("频率范围太窄，无法绘制图像")

    # 图像尺寸与像素网格一致时直接使用（原生分辨率，最清晰），否则缩放
    if img.shape == (n_rows, width):
        amp = img.astype(np.float32).T / 255.0          # -> (width, n_rows)
    else:
        pil = Image.fromarray(img).resize((width, n_rows), Image.LANCZOS)
        amp = np.asarray(pil, dtype=np.float32).T / 255.0

    # 频率映射：行 -> bin（顶部=高频）
    rows = np.arange(n_rows)
    ratio = 1.0 - rows / (n_rows - 1)
    bins = bin_low + (ratio * (bin_high - bin_low - 1)).astype(np.int64)

    # 相位连续（按全局时间推进）：每列音调与前后列无缝衔接，
    # 避免帧间相位跳变产生的条纹噪声，图案边缘锐利可扫码
    cols = np.arange(width)
    # 可选频率抖动（打散拍频条纹；注意必须搭配小数频点真实合成才有意义，
    # 整数 bin 的 IFFT 无法承载亚 bin 偏移，抖动会退化成相位噪声，故默认关闭）
    if freq_jitter > 0:
        jitter = np.random.default_rng(42).uniform(
            -freq_jitter, freq_jitter, n_rows)
        freq_units = bins.astype(np.float64) + jitter
    else:
        freq_units = bins.astype(np.float64)
    phases = 2 * np.pi * (
        (freq_units[None, :] * (cols * HOP)[:, None]) % N_FFT) / N_FFT

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
