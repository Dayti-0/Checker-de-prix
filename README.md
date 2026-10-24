# PrixMalin

Comparez en un clic les prix d'un produit chez **Aldi, Lidl, Carrefour, Intermarché, Courses U et E.Leclerc Drive**, puis le total de votre liste de courses dans chaque enseigne.

## Installer et lancer (Windows)

1. Installez **Python 3.11 à 3.14** depuis <https://www.python.org/downloads/>. Pendant l'installation, **cochez la case « Add python.exe to PATH »**.
2. Installez **Google Chrome** (ou gardez Microsoft Edge) : Intermarché et E.Leclerc s'ouvrent dans une fenêtre Chrome à part.
3. Double-cliquez sur **`lancer.bat`**. Le premier lancement installe tout (quelques minutes), propose un raccourci sur le Bureau, puis ouvre PrixMalin dans votre navigateur dès qu'il est prêt (<http://localhost:8000>).

Les lancements suivants sont rapides : rien n'est retéléchargé tant que PrixMalin n'a pas été mis à jour. Relancer `lancer.bat` alors que PrixMalin est déjà ouvert ouvre simplement sa page. Pour arrêter PrixMalin, fermez sa fenêtre noire.

- **Raccourci** : `installer-raccourci.bat` crée (ou recrée) l'icône PrixMalin sur le Bureau et dans le menu Démarrer.
- **Autre port** : si le port 8000 est pris par un autre programme, `lancer.bat` propose le port suivant (« O », ou rien pendant 20 s) et le retient. Pour en imposer un : dans une invite de commandes du dossier, `set PRIXMALIN_PORT=8010` puis `lancer.bat`.

Sur Mac/Linux :

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m backend.browser_check --install   # télécharge Chromium seulement si Chrome ou Edge manquent
python -m backend.main
```

## Sur le téléphone

Le téléphone doit être sur **le même Wi-Fi** que le PC.

1. Au démarrage, la fenêtre noire affiche l'adresse pour le téléphone (par exemple `http://192.168.1.10:8000`), un **QR code** et le **code d'accès** à 6 chiffres. On les retrouve dans **Réglages › Sur le téléphone** et **Réglages › Sécurité**.
2. Scannez le QR code avec l'appareil photo du téléphone, puis tapez le code d'accès une fois : le téléphone reste autorisé un an.

Si la page ne s'ouvre pas : autorisez Python sur les **réseaux privés** dans le pare-feu Windows et réglez le Wi-Fi du PC en réseau « privé ». Tout est expliqué, avec l'option HTTPS (Tailscale, accès en 4G), dans [docs/acces-telephone.md](docs/acces-telephone.md).

Pour réserver PrixMalin au PC : Réglages › Sécurité › décochez « Autoriser l'accès depuis le téléphone ».

## Premier réglage (2 minutes)

Ouvrez **Réglages** :

1. **Code postal** : tapez-le puis « Valider ». Les magasins Courses U et E.Leclerc les plus proches sont choisis tout seuls.
2. **Intermarché** : « Trouver les magasins proches » puis choisissez votre magasin.

Aldi et Lidl ont des prix nationaux : rien à régler. Carrefour affiche ses prix en ligne par défaut.

## Utilisation

- **Rechercher** : chaque enseigne s'affiche dès qu'elle répond, triée du moins cher au plus cher. « Le moins cher » est surligné en vert. Le tri **prix au kg / L** compare des formats différents.
- **Ma liste** : ajoutez des articles ou un produit précis (bouton **+** d'un produit), puis comparez le total de votre panier par enseigne.
- **Actualiser les prix** : relit les sites (les prix sont gardés 6 h).

## Vos données, sauvegarde et mise à jour

- Vos données (réglages, liste, navigateur de PrixMalin, journal) sont dans **`%LOCALAPPDATA%\PrixMalin`**, hors du dossier de l'application : une mise à jour ou une nouvelle copie de PrixMalin les garde. Un ancien dossier `data` à côté de `lancer.bat` y est déplacé tout seul.
- **Réglages › Mes données** : « Enregistrer une sauvegarde » (un fichier `.json`), puis « Restaurer » pour la remettre, sur ce PC ou un autre. PrixMalin garde aussi une copie de sa base par jour (7 jours) dans `%LOCALAPPDATA%\PrixMalin\backups`.
- **Mettre à jour** : fermez PrixMalin, puis double-cliquez sur **`mettre-a-jour.bat`**. PrixMalin redémarre tout seul. Réglages › À propos indique si une nouvelle version existe (vérification une fois par jour, désactivable).

## En cas de problème

| Message | Que faire |
|---------|-----------|
| « Vérification requise » | Bouton **Ouvrir le site** : une fenêtre du navigateur PrixMalin s'ouvre, validez la vérification, puis cliquez sur **J'ai terminé** en haut de PrixMalin. |
| « Magasin à choisir » | Choisissez votre magasin dans les réglages. |
| « Aucun produit » alors que le site en affiche | Le site a peut-être changé : la page **État des enseignes** (Réglages › Navigateur › Dépannage) permet d'enregistrer un rapport de diagnostic. |
| « Le port 8000 est déjà utilisé » | Un autre programme utilise le port : acceptez le port suivant proposé par `lancer.bat`. |
| « Python 3.11 ou plus est introuvable » | Réinstallez Python en cochant « Add python.exe to PATH ». |
| Le téléphone n'ouvre pas la page | Voir [docs/acces-telephone.md](docs/acces-telephone.md). |

Le journal de PrixMalin est dans `%LOCALAPPDATA%\PrixMalin\logs\prixmalin.log`.

PrixMalin utilise son propre navigateur (Chrome ou Edge s'ils sont installés, sinon Chromium), avec un profil séparé dans le dossier des données : vos cookies et choix de magasins y sont conservés.

> Usage personnel uniquement : le scraping de ces sites peut être contraire à leurs conditions d'utilisation.
