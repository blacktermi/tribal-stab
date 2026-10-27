# Tribal Stab

Stabilisation des vidéos tenues à la main. C'est l'algorithme « stab2 » écrit pour les rushs de tableaux de Tribal Print
(26 octobre 2026), sorti de la bibliothèque de rushs pour servir partout : rushs produit, vidéos YouTube, tournages clients
de Tribal Studio.

Sur les 12 extraits du banc d'essai (mains qui présentent, tableaux soulevés, caméra qui bascule, gros plans), la secousse
du mur passe de 13,8 px à 4,7 px en 4K (−66 %), mieux sur 10 extraits sur 10. Les deux témoins restent bons : le plan fixe
ne bouge pas et le travelling voulu est gardé.

## Ce qu'il fait

1. **Analyser.** Des repères sur le décor (coins, arêtes) sont suivis d'une image à l'autre au sous-pixel. Chaque repère
   est vérifié dans les deux sens. Un vote RANSAC garde le mouvement du décor et écarte ce qui bouge devant (mains,
   objet présenté).
2. **Chemin.** Il choisit la trajectoire la plus calme qui tienne dans la marge : trépied virtuel pour un plan tenu à la
   main, sinon glissement régulier, sinon mouvement adouci. Un travelling voulu n'est jamais figé.
3. **Zoom.** Il applique le plus petit agrandissement qui évite tout bord noir. Ce zoom reste constant sur tout l'extrait.
4. **Rendre.** Chaque image est redressée au sous-pixel (Lanczos) depuis la définition d'origine, puis encodée une seule
   fois (H.264, CRF 12). Le son d'origine est recopié.

L'analyse et le rendu lisent les mêmes images, à cadence fixe : chaque correction tombe sur la bonne image.

## Installer

Il faut Python 3.10 ou plus et `ffmpeg` (avec `ffprobe`) dans le PATH.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Depuis un autre projet, sans copier le code :

```bash
pip install "git+https://github.com/blacktermi/tribal-stab.git"
```

## Utiliser

```bash
tribal-stab rush.mov                          # → rush_stab.mp4 à côté, même taille, même cadence, avec le son
tribal-stab rush.mov --4k                     # rendu en 4K (petit côté à 2160, proportions gardées)
tribal-stab rush.mov --debut 7 --fin 9.5      # un extrait seulement
tribal-stab rush.mov --mains                  # des mains présentent un objet au centre : suivre le décor sur les bords
tribal-stab rush.mov --mouvement-voulu        # travelling ou panoramique : ne jamais figer en trépied
tribal-stab dossier/ -o dossier_stab/         # toutes les vidéos d'un dossier
```

Autres réglages : `--glissement` (sans rotation ni zoom), `--marge 10` (agrandissement maximal en %), `--lissage 2`
(secondes), `--taille 2160x3840`, `--ips 30`, `--crf 12`, `--sans-son`, `--sans-rapport`.

Chaque vidéo sort avec un rapport `.json` : mode choisi (`trepied`, `glissement`, `doux 2 s`…), zoom, part des repères
retenus sur le décor, correction maximale.

Depuis Python :

```python
import tribal_stab as ts

ts.stabiliser("rush.mov", "rush_stab.mp4", debut=7, fin=9.5, taille=ts.taille_4k(1080, 1920),
              reglage={**ts.REGLAGE, "zone": "bords"})

# ou étape par étape (pour un banc d'essai, des aperçus rapides) :
corr, zoom, rapport = ts.preparer("rush.mov", 7, 9.5, 30, (2160, 3840))
ts.rendre("rush.mov", 7, 2.5, 30, corr, zoom, "sortie.mp4", (2160, 3840))
```

## Vérifier

```bash
.venv/bin/python -m unittest discover tests
```

Le test fabrique un mur texturé filmé « à la main » (±12 px, ±0,6°), le stabilise, puis mesure le mouvement restant
avec une méthode indépendante (corrélation de phase). Résultat : 1,38 px d'une image à l'autre avant, 0,03 px après.

## Limites

- Vidéos SDR (BT.709). Une vidéo HDR (HLG, Dolby Vision) doit d'abord être convertie, sinon ses couleurs sortent ternes.
- Le traitement est lent : environ 8 s par seconde de 4K à 30 i/s, 16 s à 60 i/s.
- L'analyse garde les images réduites en mémoire : environ 0,5 Mo par image, soit 1 Go pour une minute à 30 i/s.
- Un plan sans décor fixe visible (ciel, mur uni, tout bouge) se stabilise mal : le rapport le signale par une faible
  `part_decor` et des `rates`.

## Licence

MIT (voir `LICENSE`) : libre d'utiliser, de modifier et de redistribuer, en gardant la mention de copyright.

## Historique

- **1.0.0 (27/10/2026)** : sortie de `stab2.py` (bibliothèque de rushs Tribal Print) en outil autonome. Le calcul reste
  le même : sur les rushs, corrections, rapports et images rendues sont identiques à l'ancienne version. Ajouts : taille et cadence lues dans la
  vidéo, son recopié, vidéo entière ou dossier, ligne de commande, test.
