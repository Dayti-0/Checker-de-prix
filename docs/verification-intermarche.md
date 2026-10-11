# Vérifier qu'Intermarché fonctionne

Intermarché protège son site avec **DataDome**, un service qui repère les robots. Les anciennes versions de PrixMalin visitaient Intermarché avec un navigateur automatisé et invisible : DataDome l'a repéré et a fini par bloquer la connexion.

Cette version change de méthode :

- PrixMalin ouvre **une fenêtre Google Chrome à part**, réservée à Intermarché (Microsoft Edge si Chrome n'est pas installé). C'est votre vrai Chrome, lancé normalement, sans aucune modification.
- Cette fenêtre a **son propre profil**, rangé dans le dossier `data\chrome-intermarche` de PrixMalin. Elle ne voit ni vos favoris, ni vos mots de passe, ni votre historique.
- Pour une recherche, PrixMalin l'ouvre **réduite** dans la barre des tâches. Elle ne passe jamais devant ce que vous faites.
- Vous pouvez la réduire, mais **laissez-la ouverte** : la session Intermarché y reste active. Si vous la fermez, PrixMalin la rouvrira (réduite) à la prochaine recherche Intermarché.
- Si Intermarché refuse la connexion, PrixMalin **s'arrête tout de suite** et ne contacte plus le site pendant un moment (30 minutes, puis 1 h, 2 h et au plus 4 h si cela recommence). Il ne réessaie jamais tout seul pendant ce temps.

Comptez une vingtaine de minutes pour les étapes 1 à 4, puis un coup d'œil le lendemain (étape 5).

## Avant de commencer : votre Chrome habituel

PrixMalin doit être **fermé** (fermez la fenêtre noire de `lancer.bat`).

1. Ouvrez votre Chrome de tous les jours.
2. Allez sur `www.intermarche.com`.

| Ce que vous voyez | Ce que cela veut dire | Que faire |
|---|---|---|
| Le site s'affiche normalement | Votre connexion n'est pas bloquée | Passez à l'étape 1 |
| Un petit puzzle à faire glisser | Intermarché veut vérifier que vous êtes une personne | Faites-le, puis passez à l'étape 1 |
| « Accès temporairement restreint » ou « Vous avez été bloqué(e) » | C'est **votre connexion** qui est bloquée, pas PrixMalin | N'insistez pas. Attendez plusieurs heures (jusqu'à 24 h) sans aller sur le site, puis refaites ce test |

## Étape 1 : mettre à jour PrixMalin

1. Lancez `lancer.bat` comme d'habitude. Il installe tout seul ce qui manque.
2. Faites une recherche simple, par exemple « farine ».
3. Vérifiez qu'Aldi, Lidl, Carrefour et Courses U affichent leurs prix comme avant.

Intermarché affiche peut-être « Magasin à choisir » : c'est normal, c'est l'étape 2.

## Étape 2 : ouvrir la fenêtre Intermarché une première fois

1. Dans PrixMalin, allez dans **Réglages › Navigateur**, ouvrez **Dépannage** et appuyez sur **« Ouvrir Intermarché (fenêtre Chrome) »**. Le bouton « Ouvrir le site » d'Intermarché, dans les résultats ou dans Réglages › Enseignes, fait la même chose.
2. Une **nouvelle fenêtre Chrome** s'ouvre sur `intermarche.com`. Elle est vide de vos habitudes : c'est voulu.
3. Dans cette fenêtre :
   - acceptez ou refusez les cookies, comme vous le feriez vous-même ;
   - promenez-vous un peu sur le site (une catégorie, un produit) ;
   - si un puzzle apparaît, faites-le **une fois**.
4. Revenez dans PrixMalin et appuyez sur **« J'ai terminé »**. Si vous avez déjà fermé la fenêtre Chrome, appuyez quand même dessus : seul Intermarché est concerné, les prix des autres enseignes ne sont pas effacés.
5. Si ce n'est pas déjà fait, choisissez votre magasin Intermarché dans **Réglages › Enseignes** (code postal, puis votre magasin dans la liste).

Si la fenêtre affiche « Accès temporairement restreint » : arrêtez-vous là et lisez « En cas de blocage » plus bas.

## Étape 3 : quelques recherches

1. Cherchez « farine » : Intermarché doit afficher des prix.
2. Faites 5 à 10 recherches différentes, espacées sur quelques minutes (« huile », « lait », « café »…).
3. Ajoutez une dizaine d'articles à votre liste de courses et comparez le panier.

Pendant ces recherches, la fenêtre Chrome d'Intermarché reste dans la barre des tâches. C'est normal : PrixMalin s'en sert sans l'afficher.

## Étape 4 : fenêtre réduite, puis redémarrage

1. Réduisez la fenêtre Chrome d'Intermarché (le trait en haut à droite) et refaites une recherche : les prix doivent s'afficher.
2. Fermez PrixMalin, relancez `lancer.bat`, refaites une recherche. Il ne doit pas y avoir de nouveau puzzle.

## Étape 5 : le lendemain

Refaites une ou deux recherches le lendemain, sans repasser par « Ouvrir le site ». Si les prix d'Intermarché s'affichent encore, tout est en ordre : la vérification n'est plus nécessaire au quotidien.

## Ce que PrixMalin peut afficher pour Intermarché

| Message | Ce que cela veut dire | Que faire |
|---|---|---|
| Des prix | Tout fonctionne | Rien |
| « Magasin à choisir » | Aucun magasin Intermarché n'est choisi | Choisissez-le dans Réglages › Enseignes |
| « Vérification requise » : « Intermarché demande une vérification… » | Intermarché veut un puzzle | Appuyez sur « Ouvrir le site », faites le puzzle dans la fenêtre Chrome d'Intermarché, appuyez sur « J'ai terminé », puis relancez la recherche. PrixMalin ne rappelle pas Intermarché tant que ce n'est pas fait (au plus 10 minutes) |
| « Intermarché bloque temporairement cette connexion. PrixMalin ne réessaiera pas avant 15 h 40. » | Intermarché refuse la connexion pour un moment. Il n'y a rien à valider | Ne faites rien. Les autres enseignes continuent de marcher. Lisez « En cas de blocage » |
| « Intermarché nécessite Google Chrome ou Microsoft Edge installé… » | Ni Chrome ni Edge n'ont été trouvés | Installez Google Chrome, puis relancez PrixMalin |
| « Une fenêtre Chrome d'Intermarché est déjà ouverte sans PrixMalin… » | La fenêtre du profil `chrome-intermarche` a été ouverte en dehors de PrixMalin | Fermez cette fenêtre, puis relancez la recherche |
| « Le site Intermarché met trop de temps à répondre. » | Le site est lent, ou la fenêtre démarrait | Relancez la recherche une minute plus tard |
| Des prix avec « Prix du 03/10 à 14 h (Intermarché : vérification requise) » | Le site n'a pas répondu, PrixMalin montre les derniers prix connus | Suivez la ligne « Vérification requise » ou « bloque temporairement » ci-dessus |

## En cas de blocage

Le message « Accès temporairement restreint » (dans la fenêtre Chrome) ou « Intermarché bloque temporairement cette connexion » (dans PrixMalin) veut dire qu'Intermarché refuse **votre connexion Internet** pendant un moment. Personne ne peut le débloquer à la main : il faut attendre.

1. **N'insistez pas.** Chaque nouvelle tentative prolonge le blocage. PrixMalin le sait : il ne contacte plus Intermarché avant l'heure affichée, même si vous relancez une recherche ou redémarrez PrixMalin. Si plusieurs recherches attendaient au même moment (deux recherches tapées à la suite, le téléphone en même temps que l'ordinateur, la recherche d'un magasin), aucune d'elles ne contacte Intermarché après le refus : la pause reste de 30 minutes au premier blocage.
2. **Faites le test de votre Chrome habituel** (début de ce document), mais une seule fois :
   - s'il est bloqué aussi, c'est la connexion : attendez plusieurs heures, jusqu'à 24 h ;
   - s'il fonctionne, notez-le pour le développeur.
3. **Après l'attente**, refaites l'étape 2 (« Ouvrir le site », puzzle seulement s'il apparaît, « J'ai terminé »).
4. Si le blocage revient alors que votre Chrome habituel fonctionne, envoyez au développeur :
   - les fichiers `data\debug\intermarche-…` les plus récents (copies de la page au moment du problème) ;
   - l'heure du blocage et ce que vous faisiez juste avant.

Évitez de redémarrer votre box en boucle pour changer d'adresse : cela ne règle pas la cause.

## Repartir de zéro (seulement si le développeur le demande)

1. Fermez PrixMalin et la fenêtre Chrome d'Intermarché.
2. Supprimez le dossier `data\chrome-intermarche`.
3. Relancez PrixMalin et refaites l'étape 2.

Vous perdez seulement la session Intermarché de PrixMalin. Le magasin choisi dans les réglages, la liste de courses et les autres enseignes ne bougent pas.
