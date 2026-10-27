"""Test sur une vidéo fabriquée : un décor fixe filmé « à la main » (secousses connues), qui doit ressortir calme.
    python -m unittest discover tests
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import tribal_stab as ts

L, H, IPS, N = 540, 960, 30, 75


def decor():
    """Un mur texturé (bruit lissé, briques claires) : de quoi accrocher les repères."""
    r = np.random.default_rng(7)
    img = cv2.GaussianBlur(r.integers(0, 255, (H * 2, L * 2), dtype=np.uint8), (0, 0), 3)
    img = cv2.normalize(img, None, 40, 215, cv2.NORM_MINMAX)
    for y in range(0, H * 2, 60):
        cv2.line(img, (0, y), (L * 2, y), 235, 3)
        for x in range((y // 60 % 2) * 45, L * 2, 90):
            cv2.line(img, (x, y), (x, y + 60), 235, 3)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def secousses():
    """Un tremblement de main : marche aléatoire lissée, ±12 px et ±0,6°."""
    r = np.random.default_rng(3)
    s = np.cumsum(r.normal(0, 1, (N, 3)), 0)
    s = np.stack([np.convolve(c, np.ones(3) / 3, "same") for c in s.T], 1)
    s -= s.mean(0)
    s /= np.abs(s).max(0)
    return s * [12, 12, 0.6]


def fabriquer(chemin):
    fond, sec = decor(), secousses()
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{L}x{H}", "-r", str(IPS), "-i", "-",
                          "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(chemin)], stdin=subprocess.PIPE)
    for dx, dy, a in sec:
        M = cv2.getRotationMatrix2D((L, H), a, 1.0)
        M[:, 2] += [dx - L / 2, dy - H / 2]
        p.stdin.write(cv2.warpAffine(fond, M, (L, H), flags=cv2.INTER_LINEAR).tobytes())
    p.stdin.close()
    p.wait()


def secousse(chemin):
    """Mouvement moyen d'une image à l'autre (px), mesuré par corrélation de phase sur le centre : indépendant de l'algorithme."""
    imgs = [i.astype(np.float32) for i in ts.images(chemin, 0, N / IPS, IPS, (L, H), gris=True)]
    c = lambda i: i[H // 4:3 * H // 4, L // 4:3 * L // 4]
    return float(np.mean([np.hypot(*cv2.phaseCorrelate(c(a), c(b))[0]) for a, b in zip(imgs, imgs[1:])]))


class TestStabilisation(unittest.TestCase):
    def test_main_levee_devient_calme(self):
        with tempfile.TemporaryDirectory() as d:
            brut, stab = Path(d) / "brut.mp4", Path(d) / "stab.mp4"
            fabriquer(brut)
            info = ts.sonder(brut)
            self.assertEqual((info["largeur"], info["hauteur"], info["ips"]), (L, H, "30"))
            r = ts.stabiliser(brut, stab)
            avant, apres = secousse(brut), secousse(stab)
            self.assertEqual(r["mode"], "trepied")
            self.assertLess(apres, avant * 0.25, f"secousse {avant:.2f} → {apres:.2f} px")
            self.assertLessEqual(r["zoom_pct"], 10)
            self.assertTrue(stab.with_suffix(".json").exists())

    def test_travelling_voulu_garde(self):
        """Un glissement régulier voulu ne doit pas être figé : la correction reste proche de zéro."""
        traj = np.zeros((60, 4)); traj[:, 0] = np.linspace(0, 40, 60)
        mode, corr, z = ts.chemin(traj, 30, False, ts.REGLAGE, L, H)
        self.assertEqual(mode, "glissement")
        self.assertLess(np.abs(corr).max(), 1e-6)

    def test_taille_4k(self):
        self.assertEqual(ts.taille_4k(1080, 1920), (2160, 3840))
        self.assertEqual(ts.taille_4k(1920, 1080), (3840, 2160))
        self.assertEqual(ts.taille_analyse((2160, 3840)), (540, 960))


if __name__ == "__main__":
    unittest.main()
