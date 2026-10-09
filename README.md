# PrixMalin

Comparez en un clic les prix d'un produit chez **Aldi, Lidl, Carrefour, Intermarché et Courses U**, puis le total de votre liste de courses dans chaque enseigne.

## Lancer l'application (Windows)

Double-cliquez sur **`lancer.bat`**. Le premier lancement installe tout (quelques minutes), puis l'application s'ouvre dans votre navigateur sur <http://localhost:8000>.

Depuis votre téléphone sur le même Wi-Fi : `http://ADRESSE-IP-DU-PC:8000`.

Sur Mac/Linux :

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m backend.main
```

## Premier réglage (2 minutes)

Ouvrez **⚙️ Réglages** :

1. **Code postal** : tapez-le puis « Valider ».
2. **Intermarché** : « Trouver les magasins proches » puis cliquez sur votre magasin.
3. **Courses U** : sur coursesu.com, ouvrez la page de votre magasin et collez son adresse (ex : `https://www.coursesu.com/drive-superu-roujan`), puis « Enregistrer ».

Aldi et Lidl ont des prix nationaux : rien à régler. Carrefour affiche ses prix en ligne par défaut.

## Utilisation

- **Rechercher** : chaque enseigne s'affiche dès qu'elle répond, triée du moins cher au plus cher. « Le moins cher » est surligné en vert. Le tri **prix au kg / L** permet de comparer des formats différents.
- **Ma liste** : ajoutez des articles (« + Ajouter « farine » à ma liste ») ou un produit précis (bouton **+** d'un produit), puis **Comparer mon panier** pour voir le total par enseigne et le total en panachant.
- **↻ Actualiser** : ignore le cache (les résultats sont gardés 6 h).

## En cas de problème

| Message | Que faire |
|---------|-----------|
| « vérification anti-robot » | Bouton **Ouvrir le site** : une fenêtre du navigateur PrixMalin s'ouvre, validez la vérification, puis cliquez sur **J'ai terminé** en haut de PrixMalin. |
| « Magasin à choisir » | Choisissez votre magasin dans les réglages (voir plus haut). |
| « Aucun produit trouvé » alors que le site en affiche | Le site a peut-être changé. La page reçue est enregistrée dans `data/debug/` pour aider à corriger le programme. |
| « injoignable » | Vérifiez votre connexion Internet. |

PrixMalin utilise son propre navigateur (Chrome ou Edge s'ils sont installés, sinon Chromium), avec un profil séparé dans `data/browser-profile` : vos cookies et choix de magasins y sont conservés. Cochez « Afficher la fenêtre du navigateur » dans les réglages pour voir ce qu'il fait.

> Usage personnel uniquement : le scraping de ces sites peut être contraire à leurs conditions d'utilisation.
