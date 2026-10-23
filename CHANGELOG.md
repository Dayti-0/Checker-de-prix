# Journal des modifications

Toutes les modifications notables de PrixMalin sont notées ici, au format
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Les versions suivent
[SemVer](https://semver.org/lang/fr/). Les notes d'une version publiée sur
GitHub sont tirées de sa section (`.github/workflows/release.yml`).

## [Non publié]

### Sécurité et exploitation (lot P7, phase A)

- Accès depuis le téléphone protégé par un code à 6 chiffres (Réglages › Sécurité et fenêtre de PrixMalin) ; adresses inconnues et demandes venues d'autres sites refusées ; réglage « Autoriser l'accès depuis le téléphone ».
- `lancer.bat` plus fiable : dossier de lancement quelconque, recherche de Python 3.11 ou plus, environnement virtuel réparé, dépendances installées seulement après un changement, page ouverte dès que PrixMalin est prêt.
- Adresse du téléphone et QR code dans la console et dans Réglages › Sur le téléphone.
- Une seule instance : un deuxième lancement ouvre la page du premier.
- Journal dans un fichier (`logs/prixmalin.log`), une ligne par erreur dans la fenêtre noire.
- Raccourci sur le Bureau et dans le menu Démarrer (`installer-raccourci.bat`).
- Données hors du dossier de l'application (`%LOCALAPPDATA%\PrixMalin`), sauvegarde et restauration (Réglages › Mes données), copie quotidienne de la base.
- Mise à jour : `mettre-a-jour.bat`, vérification d'une nouvelle version une fois par jour (Réglages › À propos).
- Premier lancement plus rapide : Chromium n'est téléchargé que si ni Chrome ni Edge ne démarrent.
- Intégration continue sous Windows, Python 3.14, Dependabot.

## [2.1.0]

Version de départ des lots P1 à P7 (fondations P0).
