import hashlib
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field

import httpx
import torch
from PIL import Image

from .config import Config, ConfigError
from .sources import Listing

# SigLIP2 beat DINOv2 clearly in the 2026-10-05 bake-off (AUC 0.94 vs 0.69, see ARCHITECTURE.md)
MODEL = "google/siglip2-base-patch16-224"
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
PHOTOS_PER_LISTING = 3
# Cosine of 1000 listings near Gent vs a catalogue reference: median 0.55, 99th percentile 0.71.
# Rescaled so the median maps to 0 and the 99th percentile to 0.5 (the default threshold), which
# keeps the keyword weights meaningful.
# ponytail: anchors measured on one reference photo; calibrate per user in `check` if they drift
PHOTO_MEDIAN, PHOTO_P99 = 0.55, 0.71

log = logging.getLogger(__name__)


def norm(s: str) -> str:
    """Case- and accent-insensitive form for substring matching."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold()


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(s))


@dataclass
class Score:
    total: float
    photo: float = 0.0
    groups: list[str] = field(default_factory=list)
    frame_hit: bool = False

    def notify(self, threshold: float) -> bool:
        return self.frame_hit or self.total >= threshold

    def reasons(self) -> str:
        parts = ["frame number in text"] if self.frame_hit else []
        parts.append(f"photo {self.photo:.2f}")
        parts += [f"keyword: {g}" for g in self.groups]
        return ", ".join(parts)


def frame_hit(listing: Listing, cfg: Config) -> bool:
    # frame numbers are often written with spaces or dashes, so compare alphanumerics only
    frame = _alnum(cfg.frame_number or "")
    return bool(frame) and frame in _alnum(f"{listing.title} {listing.description}")


def found(word: str, text: str) -> bool:
    """Substring match on normalised text, except a number never matches inside a longer
    number: "28" is not in "280", "1280" or "28.00", nor in "28.5" or "28,5"."""
    w = norm(word)
    pattern = re.escape(w)
    if w[:1].isdigit():
        pattern = r"(?<![\d.,])" + pattern
    if w[-1:].isdigit():
        pattern += r"(?![.,]?\d)"
    return re.search(pattern, text) is not None


def score(listing: Listing, cfg: Config, photo: float = 0.0) -> Score:
    if frame_hit(listing, cfg):
        return Score(total=1.0 + photo, photo=photo, frame_hit=True)
    text = norm(f"{listing.title} {listing.description}")
    groups = [n for n, g in cfg.keywords.items() if any(found(w, text) for w in g.words)]
    total = photo + sum(cfg.keywords[n].weight for n in groups)
    return Score(total=total, photo=photo, groups=groups)


def load_model():
    from transformers import AutoModel, AutoProcessor  # slow import, only when needed
    from transformers.utils import logging

    logging.disable_progress_bar()
    logging.set_verbosity_error()  # harmless token-id warnings from the unused text config
    # ponytail: loads the text tower too (~1.5 GB); the vision tower alone would do
    return AutoProcessor.from_pretrained(MODEL), AutoModel.from_pretrained(MODEL).eval()


def embed(model, images: list[Image.Image]) -> torch.Tensor:
    """(n, d) unit vectors of the whole photos."""
    processor, net = model
    with torch.inference_mode():
        out = net.get_image_features(
            **processor(images=[i.convert("RGB") for i in images], return_tensors="pt")
        )
    out = getattr(out, "pooler_output", out)  # transformers 5 returns an output object
    return torch.nn.functional.normalize(out, dim=1)


def reference_embeddings(model, cfg: Config) -> torch.Tensor:
    photos = sorted(p for p in cfg.reference_dir.glob("*") if p.suffix.lower() in PHOTO_EXT)
    if not photos:
        raise ConfigError(f"no reference photos in {cfg.reference_dir}")
    cache = cfg.data_dir / "embeddings"
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in photos:
        # model name in the key, so a model change never reuses old embeddings
        f = cache / f"{MODEL.replace('/', '--')}-{hashlib.sha256(p.read_bytes()).hexdigest()}.pt"
        log.debug("reference %s: %s", p.name, "cached" if f.exists() else "embedding")
        if not f.exists():
            torch.save(embed(model, [Image.open(p)])[0], f)
        rows.append(torch.load(f))
    return torch.stack(rows)


def photo_score(listing_embs: torch.Tensor, refs: torch.Tensor) -> float:
    """Best cosine over all listing x reference photo pairs, rescaled (see PHOTO_MEDIAN)."""
    if not len(listing_embs):
        return 0.0
    best = (listing_embs @ refs.T).max().item()
    return max(0.0, 0.5 * (best - PHOTO_MEDIAN) / (PHOTO_P99 - PHOTO_MEDIAN))


def download(client: httpx.Client, urls: list[str]) -> list[Image.Image]:
    """Photos in memory only; a broken URL or image is skipped, never fatal."""
    images = []
    for url in urls[:PHOTOS_PER_LISTING]:
        try:
            r = client.get(url)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content))
            img.load()
            images.append(img)
        except (httpx.HTTPError, OSError) as e:
            log.debug("photo skipped, %s: %s", url, e)
    return images


def listing_photo_score(model, refs: torch.Tensor, client: httpx.Client, listing: Listing) -> float:
    # ponytail: plain HTTP download; browser sources will need their Playwright context
    images = download(client, listing.photo_urls)
    if not images:
        return 0.0
    try:
        return photo_score(embed(model, images), refs)
    except Exception as e:  # noqa: BLE001, any decode or model error
        # scored on text alone and recorded, so a bad photo is not retried on every run
        log.warning("photo scoring failed for %s: %s", listing.url, e)
        return 0.0
