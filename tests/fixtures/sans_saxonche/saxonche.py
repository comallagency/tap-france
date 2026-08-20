"""Faux module saxonche : simule l'absence du paquet pour le test du §11.

Placé en tête de PYTHONPATH par la suite de tests, il prend le pas sur le vrai
paquet et fait échouer l'import exactement comme s'il n'était pas installé.
"""

raise ImportError("saxonche indisponible (simulé par la suite de tests)")
