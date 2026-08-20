"""Faux module pypdf : simule l'absence du socle de lecture PDF.

Placé en tête de PYTHONPATH par la suite de tests, il prend le pas sur le vrai
paquet et fait échouer l'import exactement comme s'il n'était pas installé.
"""

raise ImportError("pypdf indisponible (simulé par la suite de tests)")
