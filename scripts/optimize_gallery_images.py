from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
GALLERY_DIR = ROOT / 'assets' / 'galerija'
OUTPUT_DIR = GALLERY_DIR / 'optimized'
TARGET_WIDTHS = (480, 960)


def optimize_gallery_images():
    images = sorted(
        path for path in GALLERY_DIR.glob('*')
        if path.is_file() and path.suffix.lower() in {'.jpg', '.jpeg', '.png'}
    )
    if not images:
        raise FileNotFoundError(f'No gallery images found in {GALLERY_DIR}')

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    original_bytes = 0
    mobile_bytes = 0
    desktop_bytes = 0

    for path in images:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            original_bytes += path.stat().st_size
            mobile_width = min(TARGET_WIDTHS[0], image.width)
            desktop_width = min(TARGET_WIDTHS[1], image.width)
            widths = sorted({mobile_width, desktop_width})

            for width in widths:
                height = round(image.height * width / image.width)
                resized = image.resize((width, height), Image.Resampling.LANCZOS)
                output_path = OUTPUT_DIR / f'{path.stem}-{width}.webp'
                resized.save(output_path, 'WEBP', quality=82, method=6)
                size = output_path.stat().st_size
                if width == mobile_width:
                    mobile_bytes += size
                if width == desktop_width:
                    desktop_bytes += size

    mobile_saved_percent = 100 * (1 - mobile_bytes / original_bytes)
    desktop_saved_percent = 100 * (1 - desktop_bytes / original_bytes)
    print(
        f'Optimized {len(images)} images ({original_bytes:,} original bytes): '
        f'{mobile_bytes:,} bytes for mobile ({mobile_saved_percent:.1f}% smaller), '
        f'{desktop_bytes:,} bytes for desktop ({desktop_saved_percent:.1f}% smaller).'
    )


if __name__ == '__main__':
    optimize_gallery_images()
