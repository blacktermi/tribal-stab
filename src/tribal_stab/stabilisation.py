"""Stabilisation d'une vidéo tenue à la main : l'algorithme « stab2 » du chantier stabilisation de Tribal Print (26/10/2026),
sorti de la bibliothèque de rushs pour servir partout (rushs, vidéos YouTube, tournages clients).

Quatre étapes :
  1. analyser : des repères sur le décor (coins, arêtes) suivis d'une image à l'autre au sous-pixel et vérifiés dans les
                deux sens ; le vote RANSAC garde le mouvement du décor et écarte ce qui bouge devant (mains, objet présenté) ;
  2. chemin   : la trajectoire voulue, la plus calme qui tienne dans la marge : trépied virtuel pour un plan tenu à la main,
                sinon glissement régulier, sinon mouvement adouci. Un travelling voulu n'est jamais figé ;
  3. zoom     : le plus petit agrandissement qui évite tout bord noir, constant sur l'extrait (pas de zoom animé) ;
  4. rendre   : chaque image redressée au sous-pixel (Lanczos) depuis la définition d'origine, encodée une seule fois.
Analyse et rendu lisent les mêmes images, à cadence fixe : chaque correction tombe sur son image.

Les distances sont en pixels de l'image d'analyse (petit côté MESURE), puis mises à l'échelle pour le rendu.
"""
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

MESURE = 540                     # petit côté de l'image d'analyse ; en 4K, 1 px d'analyse = 4 px
# Réglage retenu par le banc d'essai de Tribal Print (36 combinaisons sur 12 extraits, 26/10/2026) :
# zone « image » (repères partout) ou « bords » (quand des mains présentent un objet au centre) ;
# modèle « complet » (glissement + rotation + zoom) ou « glissement » seul ; marge max 10 % ; lissage 2 s.
REGLAGE = {"zone": "image", "modele": "complet", "marge_max": 0.10, "sigma": 2.0}
CODAGE = ["-c:v", "libx264", "-preset", "medium", "-crf", "12", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
          "-color_trc", "bt709", "-movflags", "+faststart"]
CADENCES = [Fraction(24000, 1001), 24, 25, Fraction(30000, 1001), 30, 50, Fraction(60000, 1001), 60, 120]


def valeur(ips):
    """La cadence en nombre, qu'elle soit donnée en entier, en décimal ou en fraction (« 30000/1001 »)."""
    return float(Fraction(str(ips)))


def _fraction(texte):
    try:
        return Fraction(texte or "0")
    except (ValueError, ZeroDivisionError):     # « 0/0 » quand ffprobe ne sait pas
        return Fraction(0)


def sonder(fichier):
    """Largeur et hauteur affichées (rotation comprise), cadence, durée, présence du son."""
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(fichier)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"Vidéo illisible : {fichier}\n{r.stderr.strip()}")
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    l, h = int(v["width"]), int(v["height"])
    rot = int(float(v.get("tags", {}).get("rotate", 0) or 0))
    for sd in v.get("side_data_list", []):
        rot = int(float(sd.get("rotation", rot)))
    if abs(rot) % 180 == 90:
        l, h = h, l
    brut = _fraction(v.get("avg_frame_rate")) or _fraction(v.get("r_frame_rate")) or Fraction(30)
    proche = min(CADENCES, key=lambda c: abs(Fraction(c) - brut))      # 29,97 reste 29,97 ; une cadence variable d'iPhone revient à 30 ou 60
    ips = proche if abs(Fraction(proche) - brut) <= 0.02 * brut else round(brut)
    return {"largeur": l, "hauteur": h, "ips": str(ips), "duree": float(d["format"].get("duration") or v.get("duration") or 0),
            "son": any(s["codec_type"] == "audio" for s in d["streams"])}


def pair(n):
    return max(2, int(round(n / 2)) * 2)


def taille_4k(l, h):
    """Petit côté à 2160, proportions gardées : 1080 × 1920 → 2160 × 3840, 1920 × 1080 → 3840 × 2160."""
    k = 2160 / min(l, h)
    return pair(l * k), pair(h * k)


def taille_analyse(taille):
    """L'image d'analyse : petit côté MESURE, mêmes proportions que la sortie (2160 × 3840 → 540 × 960)."""
    l, h = taille
    k = MESURE / min(l, h)
    return int(round(l * k)), int(round(h * k))


def images(fichier, a, d, ips, taille, gris=False, filtre="lanczos"):
    """Les images de l'extrait [a, a + d] à cadence fixe, à la taille voulue ; en gris pour l'analyse, en couleur pour le rendu."""
    l, h = taille
    fmt, k = ("gray", 1) if gris else ("bgr24", 3)
    vf = f"fps={ips},scale={l}:{h}:flags={filtre}:in_color_matrix=bt709:in_range=tv,format={fmt}"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", str(fichier), "-vf", vf,
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    try:
        while brut := p.stdout.read(l * h * k):
            yield np.frombuffer(brut, np.uint8).reshape((h, l) if gris else (h, l, 3))
    finally:
        if p.poll() is None:
            p.kill()
        p.stdout.close()
        p.wait()


def masque(l, h, zone):
    """Zone « bords » : le centre est ignoré (mains et objet présenté), on ne suit que le décor autour."""
    if zone != "bords":
        return None
    m = np.full((h, l), 255, np.uint8)
    m[int(h * .12):int(h * .88), int(l * .15):int(l * .85)] = 0
    return m


# ---------- 1. Analyser ----------
def mouvement(prec, cour, zm):
    """Mouvement du décor entre deux images, mesuré au centre de l'image : [glissement x, y, rotation (rad), zoom (log)]."""
    h, l = prec.shape
    pts = cv2.goodFeaturesToTrack(prec, maxCorners=600, qualityLevel=0.01, minDistance=8, blockSize=7, mask=zm)
    if pts is None or len(pts) < 20:
        return None, 0.0
    suiv, ok, _ = cv2.calcOpticalFlowPyrLK(prec, cour, pts, None, winSize=(21, 21), maxLevel=3)
    retour, ok2, _ = cv2.calcOpticalFlowPyrLK(cour, prec, suiv, None, winSize=(21, 21), maxLevel=3)
    fiable = (ok[:, 0] == 1) & (ok2[:, 0] == 1) & (np.linalg.norm((retour - pts)[:, 0], axis=1) < 0.7)   # aller-retour cohérent
    if fiable.sum() < 12:
        return None, 0.0
    # vote RANSAC : le mouvement qui met le plus de repères d'accord est celui du décor ; ce qui bouge devant est écarté
    M, garde = cv2.estimateAffinePartial2D(pts[fiable], suiv[fiable], method=cv2.RANSAC, ransacReprojThreshold=0.8,
                                           maxIters=3000, confidence=0.999)
    if M is None:
        return None, 0.0
    centre = np.array([l / 2, h / 2])
    tc = M[:, :2] @ centre + M[:, 2] - centre     # déplacement du centre de l'image (et non du coin haut-gauche)
    return np.array([tc[0], tc[1], np.arctan2(M[1, 0], M[0, 0]), np.log(np.hypot(M[0, 0], M[1, 0]))]), float(garde.mean())


def analyser(imgs, zone):
    """Pas d'image en image (liste ou flux d'images grises) ; un pas manqué (trop peu de repères) reprend le précédent."""
    flux = iter(imgs)
    prec = next(flux)
    h, l = prec.shape
    zm, pas, parts, rates = masque(l, h, zone), [np.zeros(4)], [], 0
    for cour in flux:
        m, part = mouvement(prec, cour, zm)
        if m is None:
            rates += 1; m = pas[-1]
        pas.append(m); parts.append(part)
        prec = cour
    return np.cumsum(pas, axis=0), {"part_decor": round(float(np.mean(parts)), 2) if parts else 0.0, "rates": rates}


# ---------- 2. Chemin et 3. zoom ----------
def gauss(v, sigma):
    """Lissage gaussien par colonne ; aux bouts, la courbe est prolongée dans sa pente."""
    r = max(1, min(int(3 * sigma), len(v) - 2))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
    out = []
    for j in range(v.shape[1]):
        c = v[:, j]
        p = np.concatenate([2 * c[0] - c[r:0:-1], c, 2 * c[-1] - c[-2:-r - 2:-1]])
        out.append(np.convolve(p, k, mode="valid"))
    return np.stack(out, axis=1)


def zoom_requis(corr, l, h):
    """Le plus petit agrandissement (constant) pour que la fenêtre de sortie reste dans l'image d'origine à chaque image."""
    zs = np.arange(1.0, 1.301, 0.0025)
    coins = np.array([[-l / 2, -h / 2], [l / 2, -h / 2], [l / 2, h / 2], [-l / 2, h / 2]])
    c, s = np.cos(-corr[:, 2]), np.sin(-corr[:, 2])
    e = np.exp(corr[:, 3])
    # point d'origine q d'un coin de sortie o : q = R(-a) (o / Z - t) / e ; il doit rester dans ±l/2, ±h/2
    u = np.stack([(c[:, None] * coins[:, 0] - s[:, None] * coins[:, 1]), (s[:, None] * coins[:, 0] + c[:, None] * coins[:, 1])], -1) / e[:, None, None]
    t = corr[:, :2]
    v = np.stack([c * t[:, 0] - s * t[:, 1], s * t[:, 0] + c * t[:, 1]], -1) / e[:, None]
    for z in zs:
        q = u / z - v[:, None, :]
        if np.all(np.abs(q[..., 0]) <= l / 2 + 1e-6) and np.all(np.abs(q[..., 1]) <= h / 2 + 1e-6):
            return float(z)
    return float("inf")


def chemin(traj, ips, figer, reglage, l, h):
    """La trajectoire voulue la plus calme qui tienne dans la marge. Renvoie (mode, correction, zoom).
    figer : le plan peut devenir un trépied virtuel (tenu à la main, plan fixe) ; False pour un travelling ou un panoramique voulu."""
    traj = traj.copy()
    if len(traj) < 3:
        return "aucune", traj * 0, 1.0
    if reglage["modele"] == "glissement":
        traj[:, 2:] = 0                                  # rotation et zoom laissés tels quels
    t = np.arange(len(traj))
    essais = []
    if figer:
        essais.append(("trepied", np.repeat(((traj.max(0) + traj.min(0)) / 2)[None], len(traj), 0)))
    essais.append(("glissement", np.stack([np.polyval(np.polyfit(t, traj[:, j], 1), t) for j in range(4)], 1)))
    for k in (1, 0.5, 0.25):
        essais.append((f"doux {reglage['sigma'] * k:g} s", gauss(traj, reglage["sigma"] * k * valeur(ips))))
    for mode, voulu in essais:
        corr = voulu - traj
        z = zoom_requis(corr, l, h)
        if z <= 1 + reglage["marge_max"]:
            return mode, corr, z
    # rien ne tient : on corrige moins (le dernier essai, réduit jusqu'à tenir)
    for f in np.arange(0.9, 0, -0.1):
        z = zoom_requis(corr * f, l, h)
        if z <= 1 + reglage["marge_max"]:
            return f"{mode} réduit à {f:.0%}", corr * f, z
    return "aucune", corr * 0, 1.0


def matrice(c, z, l, h, f):
    """Correction (glissement, rotation, zoom autour du centre) puis agrandissement z, en une opération ;
    f : px d'analyse → px de l'image traitée (4 en 4K, 1 pour un aperçu à la taille d'analyse)."""
    a = z * np.exp(c[3]) * np.array([[np.cos(c[2]), -np.sin(c[2])], [np.sin(c[2]), np.cos(c[2])]])
    centre = np.array([l / 2, h / 2])
    b = z * np.array([c[0], c[1]]) * f + centre - a @ centre
    return np.hstack([a, b[:, None]])


# ---------- 4. Rendre ----------
def rendre(fichier, a, d, ips, corr, z, sortie, taille, son=False, codage=None):
    """À la taille voulue, au sous-pixel (Lanczos), encodé une fois pour toutes ; son d'origine recopié si son=True."""
    l, h = taille
    audio = ["-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", str(fichier)] if son else []
    pistes = ["-map", "0:v", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "192k", "-shortest"] if son else []
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{l}x{h}", "-r", str(ips),
                            "-i", "-", *audio, "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=1",
                            *pistes, *(codage or CODAGE), str(sortie)], stdin=subprocess.PIPE)
    f = l / taille_analyse(taille)[0]
    for img, c in zip(images(fichier, a, d, ips, taille), corr):
        enc.stdin.write(cv2.warpAffine(img, matrice(c, z, l, h, f), (l, h), flags=cv2.INTER_LANCZOS4,
                                       borderMode=cv2.BORDER_REPLICATE).tobytes())
    enc.stdin.close()
    if enc.wait():
        sys.exit(f"Échec de l'encodage : {sortie}")


def apercu(imgs, corr, z):
    """Le même redressement sur les images d'analyse : pour essayer vite des réglages, sans rendre la pleine définition."""
    h, l = imgs[0].shape
    return np.stack([cv2.warpAffine(i, matrice(c, z, l, h, 1), (l, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                     for i, c in zip(imgs, corr)])


def preparer(fichier, a, b, ips, taille, figer=True, reglage=None):
    """Analyse et chemin de l'extrait [a, b] : (correction, zoom, rapport). taille : celle du rendu, qui fixe celle de l'analyse."""
    reglage = reglage or REGLAGE
    la, ha = taille_analyse(taille)
    traj, info = analyser(images(fichier, a, b - a, ips, (la, ha), gris=True, filtre="area"), reglage["zone"])
    mode, corr, z = chemin(traj, ips, figer, reglage, la, ha)
    k = taille[0] / la
    return corr, z, {"mode": mode, "zoom_pct": round((z - 1) * 100, 2), "zone": reglage["zone"], "modele": reglage["modele"], **info,
                     "correction_max_px": round(float(np.abs(corr[:, :2]).max() * k), 1),
                     "rotation_max_deg": round(float(np.degrees(np.abs(corr[:, 2]).max())), 2)}


def stabiliser(fichier, sortie, debut=0.0, fin=None, ips=None, taille=None, figer=True, reglage=None, son=True, rapport=True,
               codage=None):
    """Une vidéo (ou l'extrait [debut, fin]) : analyse, chemin, rendu, et un petit rapport .json à côté de la vidéo.
    Par défaut : vidéo entière, cadence, taille et son d'origine."""
    s = sonder(fichier)
    fin = s["duree"] if fin is None else min(fin, s["duree"])
    ips = ips or s["ips"]
    taille = taille or (pair(s["largeur"]), pair(s["hauteur"]))
    corr, z, r = preparer(fichier, debut, fin, ips, taille, figer, reglage)
    rendre(fichier, debut, fin - debut, ips, corr, z, sortie, taille, son=son and s["son"], codage=codage)
    r = {**r, "source": str(fichier), "debut": debut, "fin": round(fin, 3), "ips": str(ips), "taille": list(taille)}
    if rapport:
        Path(sortie).with_suffix(".json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    return r
