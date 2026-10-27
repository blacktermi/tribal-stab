"""Ligne de commande : tribal-stab <vidéo ou dossier> [...] [-o sortie]."""
import argparse
import sys
import time
from pathlib import Path

from . import __version__
from .stabilisation import CODAGE, REGLAGE, sonder, stabiliser, taille_4k

VIDEOS = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}


def entrees(chemins):
    for c in map(Path, chemins):
        if c.is_dir():
            yield from sorted(p for p in c.iterdir() if p.suffix.lower() in VIDEOS and not p.stem.endswith("_stab"))
        elif c.exists():
            yield c
        else:
            sys.exit(f"Introuvable : {c}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="tribal-stab", description="Stabilise des vidéos tenues à la main (repères sur le décor, "
                                "vote RANSAC, trépied virtuel, zoom minimal sans bord noir, rendu sous-pixel).")
    p.add_argument("entrees", nargs="+", help="vidéos ou dossiers de vidéos")
    p.add_argument("-o", "--sortie", help="fichier (une seule vidéo) ou dossier ; par défaut <nom>_stab.mp4 à côté de la vidéo")
    p.add_argument("--debut", type=float, default=0.0, help="début de l'extrait, en secondes")
    p.add_argument("--fin", type=float, help="fin de l'extrait, en secondes (par défaut : la fin de la vidéo)")
    p.add_argument("--mains", action="store_true", help="des mains présentent un objet au centre : ne suivre que le décor sur les bords")
    p.add_argument("--mouvement-voulu", action="store_true", help="travelling ou panoramique voulu : ne jamais figer en trépied")
    p.add_argument("--glissement", action="store_true", help="corriger le glissement seul (ni rotation ni zoom)")
    p.add_argument("--marge", type=float, default=REGLAGE["marge_max"] * 100, help="agrandissement maximal, en %% (défaut : 10)")
    p.add_argument("--lissage", type=float, default=REGLAGE["sigma"], help="lissage du mouvement adouci, en secondes (défaut : 2)")
    p.add_argument("--4k", dest="quatre_k", action="store_true", help="rendu en 4K : petit côté à 2160, proportions gardées")
    p.add_argument("--taille", help="taille du rendu, LARGEURxHAUTEUR (par défaut : celle de la vidéo)")
    p.add_argument("--ips", help="cadence du rendu (par défaut : celle de la vidéo)")
    p.add_argument("--crf", type=int, default=12, help="qualité H.264, plus bas = meilleur (défaut : 12)")
    p.add_argument("--sans-son", action="store_true", help="ne pas recopier le son")
    p.add_argument("--sans-rapport", action="store_true", help="ne pas écrire le rapport .json à côté de la vidéo")
    p.add_argument("--version", action="version", version=f"tribal-stab {__version__}")
    a = p.parse_args(argv)

    liste = list(entrees(a.entrees))
    reglage = {"zone": "bords" if a.mains else "image", "modele": "glissement" if a.glissement else "complet",
               "marge_max": a.marge / 100, "sigma": a.lissage}
    codage = [x if CODAGE[i - 1] != "-crf" else str(a.crf) for i, x in enumerate(CODAGE)]
    sortie = Path(a.sortie) if a.sortie else None
    if sortie and len(liste) > 1 and sortie.suffix:
        sys.exit("Plusieurs vidéos : -o doit être un dossier.")
    for e in liste:
        if sortie is None:
            s = e.with_name(f"{e.stem}_stab.mp4")
        elif sortie.suffix:
            s = sortie
        else:
            sortie.mkdir(parents=True, exist_ok=True)
            s = sortie / f"{e.stem}_stab.mp4"
        taille = None
        if a.taille:
            taille = tuple(int(x) for x in a.taille.lower().split("x"))
        elif a.quatre_k:
            info = sonder(e)
            taille = taille_4k(info["largeur"], info["hauteur"])
        t0 = time.time()
        r = stabiliser(e, s, a.debut, a.fin, a.ips, taille, not a.mouvement_voulu, reglage, not a.sans_son, not a.sans_rapport,
                       codage=codage)
        print(f"{e.name} → {s}  ·  {r['mode']}, zoom {r['zoom_pct']:g} %, correction max {r['correction_max_px']:g} px, "
              f"{r['taille'][0]} × {r['taille'][1]}, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
