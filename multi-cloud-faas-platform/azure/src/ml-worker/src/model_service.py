from pathlib import Path
from PIL import Image
from collections import Counter

import torch
import torchvision.transforms as transforms
import numpy as np
import os

"""
Species classification service.

This module loads the fine-tuned species classification model and predicts the
species label for each cropped animal image produced by MegaDetector.
"""

MODEL_PT_PATH = os.getenv("MODEL_PT_PATH", "./models/model.pt")

CLASSES = [
    'Alectura_lathami', 'Antechinus_agilis', 'Bos_taurus',
    'Burhinus_grallarius', 'Canis_familiaris',
    'Chalcophaps_longirostris', 'Colluricincla_harmonica',
    'Corcorax_melanorhamphos', 'Dacelo_novaeguineae',
    'Dama_dama', 'Eopsaltria_australis', 'Felis_catus',
    'Geopelia_humeralis', 'Gymnorhina_tibicen', 'Homo_sapiens',
    'Isoodon_macrourus', 'Lepus_europaeus', 'Macropus_giganteus',
    'Menura_novaehollandiae', 'Mus_musculus',
    'Oryctolagus_cuniculus', 'Perameles_nasuta',
    'Pitta_versicolor', 'Rattus', 'Rattus_fuscipes',
    'Rattus_rattus', 'Strepera_graculina', 'Sus_scrofa',
    'Tachyglossus_aculeatus', 'Thylogale_stigmatica',
    'Trichosurus_caninus', 'Trichosurus_cunninghami',
    'Trichosurus_vulpecula', 'Varanus_varius',
    'Vombatus_ursinus', 'Vulpes_vulpes', 'Wallabia_bicolor',
    'Canis_dingo', 'Capra_hircus', 'Casuarius_casuarius',
    'Heteromyias_cinereifrons', 'Hypsiprymnodon_moschatus',
    'Megapodius_reinwardt', 'Notamacropus_rufogriseus',
    'Orthonyx_spaldingii', 'Uromys_caudimaculatus'
]


def get_device():
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


DEVICE = get_device()

transform = transforms.Compose([
    transforms.Resize((480, 480)),
    transforms.ToTensor(),
])

_model = None


# Cache the loaded model globally so repeated API calls do not reload the model
# from disk every time.
def load_species_model():
    global _model

    if _model is None:
        model = torch.load(MODEL_PT_PATH, map_location=DEVICE, weights_only=False)
        model.eval()
        model.to(DEVICE)
        _model = model

    return _model


@torch.no_grad()
def predict_species(crop_image_path: str) -> tuple[str, float]:
    """
    Predict the species of a cropped animal image.

    Returns the scientific species name and the model confidence score.
    """

    model = load_species_model()

    img = Image.open(crop_image_path).convert("RGB")
    img = transform(img)
    img = img.unsqueeze(0)
    img = img.permute(0, 2, 3, 1)
    img = img.to(DEVICE)

    logits = model(img)
    probs = torch.softmax(logits, dim=1)[0].cpu().numpy()

    best_idx = int(np.argmax(probs))
    species = CLASSES[best_idx]
    confidence = float(probs[best_idx])

    return species, confidence


def classify_crops(crop_paths: list[Path], min_confidence: float = 0.5) -> dict:
    counter = Counter()

    for crop_path in crop_paths:
        species, confidence = predict_species(str(crop_path))
        print(f"{crop_path.name} -> {species} ({confidence:.4f})")

        if confidence >= min_confidence:
            counter[species] += 1

    return dict(counter)