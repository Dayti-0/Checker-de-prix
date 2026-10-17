# Vérifier qu'E.Leclerc Drive fonctionne

E.Leclerc Drive protège son site avec **DataDome**, le même service qu'Intermarché. PrixMalin s'y prend donc de la même façon :

- PrixMalin ouvre **une fenêtre Google Chrome à part**, réservée à E.Leclerc (Microsoft Edge si Chrome n'est pas installé). C'est votre vrai Chrome, lancé normalement, sans aucune modification.
- Cette fenêtre a **son propre profil**, rangé dans le dossier `data\chrome-leclerc` de PrixMalin. Elle ne voit ni vos favoris, ni vos mots de passe, ni votre historique, ni la fenêtre d'Intermarché.
- Pour une recherche, PrixMalin l'ouvre **réduite** dans la barre des tâches. Elle ne passe jamais devant ce que vous faites. La première fois, elle s'ouvre aussi (réduite) au moment où PrixMalin cherche le drive le plus proche de chez vous.
- Vous pouvez la réduire, mais **laissez-la ouverte**. Si vous la fermez, PrixMalin la rouvrira (réduite) à la prochaine recherche E.Leclerc.
- PrixMalin ne clique jamais à votre place : ni sur le bandeau des cookies, ni sur une vérification.
- Si E.Leclerc refuse la connexion (« Access blocked », « Accès temporairement restreint »), PrixMalin **s'arrête tout de suite** et ne contacte plus le site pendant un moment (30 minutes, puis 1 h, 2 h et au plus 4 h si cela recommence). Il ne réessaie jamais tout seul pendant ce temps.

Les structures du site utilisées par PrixMalin ont été relevées sur des pages réelles de **2025**. Le site a pu changer depuis : cette vérification sert à le savoir. Comptez une demi-heure.

## Ce qu'il faudra peut-être m'envoyer

Les fichiers utiles sont dans le dossier `data\debug` de PrixMalin, et dans le **diagnostic** (page « État des enseignes », bouton « Télécharger le diagnostic ») :

- `leclerc-…-empty.html` : une recherche sans produit ;
- `leclerc-…-stores.json` : une liste des drives que PrixMalin n'a pas su lire ;
- `leclerc-…-sample.html` : des pages de recherche gardées exprès (voir l'étape 6) ;
- `leclerc-…-error.html`, `leclerc-…-error.txt` (la réponse brute du site) ou `-blocked.html` : une recherche en erreur ou bloquée.

Ces fichiers ne contiennent pas vos identifiants : le panier d'un drive où vous n'êtes pas connecté est vide.

## Étape 1 : la fenêtre E.Leclerc

1. Lancez `lancer.bat`, puis indiquez votre code postal dans **Réglages › Localisation** (s'il n'y est pas déjà).
2. Une **deuxième fenêtre Chrome** apparaît dans la barre des tâches (réduite) : c'est celle d'E.Leclerc. Elle cohabite avec celle d'Intermarché.
3. Ouvrez-la une fois. Si le bandeau des cookies est affiché, répondez-y **vous-même**, comme vous le feriez d'habitude. Si un petit puzzle apparaît, faites-le une fois.

## Étape 2 : le drive choisi automatiquement

1. Dans **Réglages › Enseignes**, la ligne E.Leclerc doit afficher « Choisi automatiquement : E.Leclerc Drive … (≈ … km) ».
2. Vérifiez que c'est bien **le drive le plus proche** de chez vous. Appuyez sur « Changer » : la liste montre les 8 plus proches (drives et retraits piétons). Un retrait piéton n'est jamais choisi automatiquement.
3. Si un message d'erreur apparaît à la place (vérification, liste vide…) :
   - notez le message ;
   - joignez le fichier `data\debug\leclerc-…-stores.json` s'il existe ;
   - essayez l'autre méthode : menu « ⋯ » d'E.Leclerc › **« Ouvrir le site »**, choisissez votre drive sur le site (« Choisir ce Drive »), puis appuyez sur **« J'ai terminé »** dans PrixMalin. Le drive doit apparaître dans Réglages.
4. Dites-moi si la liste contient des drives « Ouverture prochaine », ou des drives sans distance.

## Étape 3 : les prix

Cherchez « farine », « eau » et « café ». E.Leclerc doit afficher des produits. Puis comparez, sur le site, deux produits en promotion :

| Sur le site | Dans PrixMalin |
|---|---|
| « Avantage immédiat » (prix barré) | Le prix **remisé**, l'ancien prix barré, et le prix au kg ou au litre de la promotion |
| « Le 2ème à -60 % » ou « Le 3ème offert » | Le prix normal, avec le texte de l'offre |
| « Recevez 20 % en Ticket E.Leclerc » | Le prix normal, sans promotion (ce n'est pas une baisse en caisse) |

Notez tout écart de prix, avec le nom du produit.

## Étape 4 : le nombre de produits

Cherchez « eau » : le nombre de produits lus par PrixMalin (« N produits lus » sous la colonne E.Leclerc, vue « Par enseigne ») doit être proche du nombre affiché par le site. Si le fichier `data\logs` contient « truncated » pour E.Leclerc, dites-le moi : il manque alors la lecture des pages suivantes.

## Étape 5 : aucun produit

Cherchez un mot qui n'existe pas, par exemple « zzqx ». PrixMalin doit afficher « Aucun produit », pas une erreur. Envoyez-moi le fichier `data\debug\leclerc-…-empty.html` créé à ce moment : il sert à figer la forme réelle de cette page.

## Étape 6 : garder quelques pages de recherche

1. Fermez PrixMalin. Dans la fenêtre de commande, lancez-le avec la variable `PRIXMALIN_DEBUG_LECLERC=1` :

   ```bat
   set PRIXMALIN_DEBUG_LECLERC=1
   lancer.bat
   ```

2. Faites 2 ou 3 recherches. Chaque page de recherche est gardée dans `data\debug\leclerc-…-sample.html` (5 au plus).
3. Ouvrez l'un de ces fichiers avec le Bloc-notes et cherchez `pnlElementProduit`, `sCodeEAN` et `sLibelleMarque` : dites-moi lesquels sont présents, et envoyez-moi le fichier. Il remplacera les pages de 2025 dans les tests.
4. Relancez ensuite PrixMalin normalement (sans la variable).

## Étape 7 : après une pause

Laissez PrixMalin ouvert **plus de 20 minutes** sans chercher, puis refaites une recherche E.Leclerc : elle doit marcher du premier coup (PrixMalin revisite d'abord la page de votre drive).

## Étape 8 : changer de drive

Choisissez un autre drive dans la liste, puis cherchez « farine » : les prix doivent changer, sans message « session expirée ».

## Étape 9 : coller l'adresse de son drive

Sur le site, copiez l'adresse de votre drive dans la barre d'adresse (page d'accueil du drive ou page d'une recherche, par exemple `https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx`). Dans PrixMalin : Réglages › Enseignes › E.Leclerc › « Changer » › « Saisir l'adresse à la main », collez-la et enregistrez : elle doit être acceptée.

## Étape 10 : les images

Les vignettes des produits E.Leclerc (`fdN-photos.leclercdrive.fr`) s'affichent-elles dans PrixMalin ? Sinon un dessin les remplace : ce n'est pas grave, mais dites-le moi.

## En cas de vérification ou de blocage

| Ce que vous voyez | Ce que cela veut dire | Que faire |
|---|---|---|
| « Vérification requise » dans PrixMalin | E.Leclerc veut vérifier que vous êtes une personne | « Ouvrir le site », faites le puzzle dans la fenêtre E.Leclerc, puis « J'ai terminé » |
| « Access blocked » ou « Accès temporairement restreint » dans la fenêtre | Votre connexion est bloquée pour un moment | N'insistez pas : PrixMalin se met en pause tout seul. Notez le texte exact (anglais ou français) |

## Dernière chose : la mémoire

Avec les deux fenêtres dédiées ouvertes (Intermarché et E.Leclerc), l'ordinateur reste-t-il fluide ? Si ce n'est pas le cas, dites-le moi.
