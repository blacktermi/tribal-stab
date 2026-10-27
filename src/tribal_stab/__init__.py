"""tribal-stab : stabilisation des vidéos tenues à la main (algorithme « stab2 » de Tribal Print, 26/10/2026)."""
from .stabilisation import (CODAGE, MESURE, REGLAGE, analyser, apercu, chemin, gauss, images, masque, matrice, mouvement,
                            preparer, rendre, sonder, stabiliser, taille_4k, taille_analyse, valeur, zoom_requis)

__version__ = "1.0.0"
__all__ = ["CODAGE", "MESURE", "REGLAGE", "analyser", "apercu", "chemin", "gauss", "images", "masque", "matrice", "mouvement",
           "preparer", "rendre", "sonder", "stabiliser", "taille_4k", "taille_analyse", "valeur", "zoom_requis"]
