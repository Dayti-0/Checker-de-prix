# Vérifications sur le PC Windows (lot P7)

Liste à suivre une fois sur le vrai PC, après la fusion du lot P7. Cochez au fur et à mesure ; notez ce qui ne va pas (message exact, capture de la fenêtre noire, fichier `logs\prixmalin.log`).

Le dossier des données est `%LOCALAPPDATA%\PrixMalin` (tapez-le dans la barre d'adresse de l'Explorateur).

## Lancement (`lancer.bat`)

- [ ] **Chemin avec espaces et accents** : copiez le dossier de PrixMalin dans `C:\Users\<vous>\Documents\Mes Logiciels\Comparé (test)` et double-cliquez sur `lancer.bat` : tout s'installe et la page s'ouvre.
- [ ] **Lancement depuis un autre dossier** : dans une invite de commandes placée ailleurs (`cd C:\`), tapez le chemin complet de `lancer.bat` entre guillemets : même résultat.
- [ ] **Premier lancement** : `[1/4] Creation de l'environnement virtuel`, `[2/4] Installation des dependances`, `[3/4] Verification du navigateur` (Chrome ou Edge trouvé : **aucun téléchargement de Chromium**), question « Creer un raccourci PrixMalin sur le Bureau ? (O/N) », puis la page s'ouvre **dès que** PrixMalin est prêt (plus d'attente fixe de 4 s). Notez la durée totale.
- [ ] **Deuxième lancement** : `Environnement virtuel pret`, `Dependances a jour`, `Navigateur pret`, sans question et **sans téléchargement** (aucun appel à PyPI ; débranchez Internet pour le vérifier). Notez la durée.
- [ ] **venv cassé** : renommez `venv\Scripts\python.exe` en `python.old`, relancez : « L'environnement virtuel ne marche plus : il est recree », puis tout fonctionne.
- [ ] **Python introuvable** (facultatif, sur un PC sans Python) : message en français qui rappelle la case « Add python.exe to PATH ».
- [ ] **Port** : `set PRIXMALIN_PORT=8010` puis `lancer.bat` dans la même invite : la page s'ouvre sur `http://localhost:8010`.

## Une seule instance

- [ ] PrixMalin ouvert, relancez `lancer.bat` : « PrixMalin est déjà ouvert : http://localhost:8000 », la page s'ouvre dans le navigateur, la deuxième fenêtre se ferme ; aucun deuxième navigateur ne démarre.
- [ ] Port pris par autre chose (par exemple `python -m http.server 8000` dans une autre invite) : message « Le port 8000 est déjà utilisé par un autre programme » qui propose `set PRIXMALIN_PORT=8001`.

## Raccourci

- [ ] Après « O » : icône **PrixMalin** sur le Bureau et dans le menu Démarrer (icône PrixMalin si `frontend\icons\prixmalin.ico` existe, sinon celle de Windows). Le raccourci lance PrixMalin fenêtre réduite et ouvre la page.
- [ ] `installer-raccourci.bat` lancé à la main recrée les raccourcis (chemin avec espaces et accents compris).

## Données et sauvegarde

- [ ] **Déplacement de `data`** : sur un PC qui avait déjà PrixMalin (dossier `data` à côté de `lancer.bat`), le premier lancement affiche « Déplacement des données de PrixMalin vers … » ; le dossier `data` disparaît, `%LOCALAPPDATA%\PrixMalin` contient la base, `browser-profile`, `chrome-intermarche`… ; la liste de courses et les magasins choisis sont toujours là.
- [ ] Fenêtre Chrome d'Intermarché laissée ouverte pendant ce premier lancement : `data` est gardé (rien de perdu), un message dans le journal ; le déplacement se fait au lancement suivant, fenêtres Chrome fermées.
- [ ] Réglages › Mes données › **Enregistrer une sauvegarde** : un fichier `prixmalin-sauvegarde-AAAA-MM-JJ.json` est téléchargé.
- [ ] Videz la liste, puis **Restaurer** ce fichier (« Les garder et ajouter ce qui manque ») : la liste revient. Même essai avec « Les remplacer ».
- [ ] Le lendemain : `%LOCALAPPDATA%\PrixMalin\backups` contient une copie `prixmalin-AAAA-MM-JJ.db` par jour (7 au plus).

## Journal

- [ ] `%LOCALAPPDATA%\PrixMalin\logs\prixmalin.log` existe, commence par la ligne des versions (PrixMalin, Python, Playwright, Windows) puis « Browser started (chrome, headless) » à la première recherche.
- [ ] Une erreur (recherche avec Internet débranché) : une seule ligne dans la fenêtre noire, le détail complet dans le fichier.
- [ ] Le code d'accès n'apparaît **jamais** dans `prixmalin.log` (cherchez ses 6 chiffres).

## Téléphone et code d'accès

- [ ] La fenêtre noire affiche l'adresse `http://192.168.x.x:8000`, le code d'accès et un QR code lisible par l'appareil photo du téléphone.
- [ ] Windows demande l'accès réseau pour Python : cochez « Réseaux privés ». Le Wi-Fi du PC est en profil « Privé ».
- [ ] Sur le téléphone : l'écran « Code d'accès » s'affiche ; un code faux donne « Code incorrect » ; le bon code ouvre PrixMalin ; le lendemain, plus de code demandé.
- [ ] Réglages › Sécurité sur le PC : **Changer le code** → le téléphone redemande le code.
- [ ] Réglages › Sécurité : décochez « Autoriser l'accès depuis le téléphone » → le téléphone est refusé tout de suite ; au redémarrage, la fenêtre noire dit « Accès depuis le téléphone désactivé ». Recochez, redémarrez : le téléphone revient.
- [ ] Réglages › Sur le téléphone : adresse, QR code, lien d'aide.
- [ ] Facultatif : Tailscale (`tailscale serve --bg 8000`), voir `docs/acces-telephone.md`, puis le téléphone en 4G.

## Mise à jour

- [ ] Réglages › À propos : version affichée ; **Vérifier maintenant** répond « Vous avez la dernière version » ou « Aucune version publiée pour l'instant ».
- [ ] Dossier venu de git : PrixMalin fermé, double-clic sur `mettre-a-jour.bat` → `git pull --ff-only`, puis PrixMalin redémarre.
- [ ] Dossier venu d'un zip, **avant** la première version publiée : `mettre-a-jour.bat` dit « Aucune version publiee pour l'instant : rien a mettre a jour », puis relance PrixMalin (pas de message sur Internet).
- [ ] Dossier venu d'un zip (après la première version publiée) : `mettre-a-jour.bat` télécharge `PrixMalin-x.y.z.zip`, remplace les fichiers, garde `venv` et les données, puis relance.
- [ ] `mettre-a-jour.bat` avec PrixMalin ouvert : « PrixMalin est ouvert : fermez sa fenetre noire… ».

## Intégration continue

- [ ] Au premier envoi de la branche sur GitHub : jobs « Tests (Python 3.11 / 3.13 / 3.14) » et « Tests Windows (Python 3.13) » verts. Un échec propre à Windows est à corriger avant la fusion (artefacts `test-artifacts-windows-…`).
