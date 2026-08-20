"""Faux module lxml : simule l'absence du socle XML.

Placé en tête de PYTHONPATH par la suite de tests, il prend le pas sur le vrai
paquet et fait échouer l'import exactement comme s'il n'était pas installé.
"""

raise ImportError("lxml indisponible (simulé par la suite de tests)")
