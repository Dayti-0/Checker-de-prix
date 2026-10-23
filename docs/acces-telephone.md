# Utiliser PrixMalin depuis le téléphone

PrixMalin tourne sur le PC. Le téléphone l'ouvre dans son navigateur, comme un site, tant qu'il est sur **le même Wi-Fi** que le PC.

## 1. Ouvrir PrixMalin sur le téléphone

1. Lancez PrixMalin sur le PC (`lancer.bat` ou le raccourci du Bureau).
2. La fenêtre noire affiche l'adresse pour le téléphone, par exemple `http://192.168.1.10:8000`, un **QR code** et le **code d'accès** à 6 chiffres. On les retrouve dans PrixMalin, sur le PC : **Réglages › Sur le téléphone** (adresse et QR code) et **Réglages › Sécurité** (code d'accès).
3. Sur le téléphone, connecté au même Wi-Fi : scannez le QR code avec l'appareil photo, ou tapez l'adresse dans le navigateur.
4. PrixMalin demande le code d'accès : tapez les 6 chiffres affichés sur le PC. Le téléphone reste autorisé pendant un an.

Astuce : dans le menu du navigateur du téléphone, « Ajouter à l'écran d'accueil » crée une icône PrixMalin.

### Le code d'accès

- Il empêche une autre personne du même Wi-Fi (invités, voisins sur un Wi-Fi partagé) d'utiliser votre PrixMalin.
- Sur le PC lui-même, aucun code n'est demandé.
- **Changer le code** (Réglages › Sécurité) : tous les téléphones déjà autorisés doivent taper le nouveau code. Faites-le si quelqu'un a vu le code.
- Après 5 codes faux en une minute, le téléphone doit attendre une minute.

### Ne plus autoriser le téléphone

Réglages › Sécurité › décochez **Autoriser l'accès depuis le téléphone**. Les téléphones sont refusés tout de suite ; au prochain démarrage, PrixMalin n'écoute plus que sur le PC.

## 2. Le téléphone n'arrive pas à ouvrir la page

| Ce que vous voyez | Que faire |
|---|---|
| La page ne charge pas, « Site inaccessible » | Le téléphone est-il sur le même Wi-Fi que le PC (pas en 4G, pas sur le Wi-Fi « invités » de la box) ? Voir aussi le pare-feu ci-dessous. |
| « Adresse inconnue de PrixMalin » | Utilisez l'adresse affichée par PrixMalin (avec les chiffres), pas un autre nom. |
| « Code incorrect » | Retapez le code affiché **en ce moment** dans Réglages › Sécurité (il a peut-être été changé). |
| « Trop d'essais » | Attendez une minute. |
| « L'accès depuis le téléphone est désactivé » | Réglages › Sécurité sur le PC, cochez « Autoriser l'accès depuis le téléphone ». |
| L'adresse a changé d'un jour à l'autre | La box donne parfois une autre adresse au PC : rescannez le QR code. Pour une adresse fixe, réservez-la dans les réglages de la box (« bail DHCP statique »). |

### Pare-feu Windows et réseau « privé »

Au premier lancement, Windows demande s'il faut autoriser Python à communiquer sur le réseau :

1. Cochez **Réseaux privés** (domicile), puis **Autoriser l'accès**.
2. Vérifiez que le Wi-Fi du PC est un réseau **privé** : Paramètres › Réseau et Internet › Wi-Fi › (votre réseau) › Type de profil réseau : **Privé**. Sur un réseau « public », Windows bloque le téléphone.

Si vous avez cliqué « Annuler » par erreur : Panneau de configuration › Pare-feu Windows Defender › **Autoriser une application ou une fonctionnalité via le Pare-feu Windows Defender** › Modifier les paramètres › cochez **Python** dans la colonne **Privé** (s'il y a plusieurs lignes Python, cochez-les toutes).

Certaines box isolent les appareils du Wi-Fi entre eux (« isolation des clients », réseau invités) : désactivez-la, ou connectez le téléphone au Wi-Fi principal.

## 3. Pourquoi HTTPS ? (facultatif)

Sur le Wi-Fi, PrixMalin s'ouvre en `http://`. C'est suffisant pour comparer les prix, mais les navigateurs réservent certaines fonctions aux adresses `https://` :

- l'application installée qui marche **hors ligne** (en magasin sans réseau) ;
- le bouton **Partager** et la copie dans le presse-papiers ;
- l'accès **en 4G**, hors de la maison (avec Tailscale).

Deux façons de l'obtenir, au choix.

### Option A : Tailscale (conseillée, marche aussi en 4G)

[Tailscale](https://tailscale.com) relie vos appareils entre eux, chiffré, où qu'ils soient. Gratuit pour un usage personnel.

1. Installez Tailscale sur le PC et sur le téléphone, et connectez-les **au même compte**.
2. Dans la console d'administration de Tailscale (site web), onglet **DNS** : activez **MagicDNS** puis **HTTPS Certificates**.
3. Sur le PC, PrixMalin lancé, ouvrez une invite de commandes et tapez :

   ```
   tailscale serve --bg 8000
   ```

   (remplacez 8000 si vous avez changé `PRIXMALIN_PORT`). Tailscale affiche l'adresse, par exemple `https://mon-pc.tail1234.ts.net`.
4. Sur le téléphone (Tailscale activé), ouvrez cette adresse : en Wi-Fi comme en 4G. Le code d'accès est demandé une fois, comme sur le Wi-Fi.

Pour arrêter : `tailscale serve --https=443 off` (ou `tailscale serve reset`).

PrixMalin accepte les adresses `*.ts.net` et reconnaît les demandes passées par Tailscale : elles demandent toujours le code d'accès, même si Tailscale les fait arriver depuis le PC.

### Option B : mkcert (Wi-Fi de la maison seulement)

[mkcert](https://github.com/FiloSottile/mkcert) crée un certificat reconnu par vos propres appareils.

1. Sur le PC, installez mkcert, puis dans une invite de commandes :

   ```
   mkcert -install
   mkcert localhost 127.0.0.1 192.168.1.10 mon-pc.local
   ```

   (mettez l'adresse et le nom de votre PC : ceux de Réglages › Sur le téléphone). Deux fichiers sont créés, par exemple `localhost+3.pem` et `localhost+3-key.pem`.
2. Installez le certificat racine de mkcert sur le téléphone (`mkcert -CAROOT` donne le dossier du fichier `rootCA.pem`) :
   - Android : Paramètres › Sécurité › Chiffrement et identifiants › Installer un certificat › Certificat CA ;
   - iPhone : envoyez-vous le fichier, installez le profil, puis Réglages › Général › Informations › Réglages des certificats : activez la confiance.
3. Indiquez les deux fichiers à PrixMalin avant de le lancer, dans l'invite de commandes du dossier de PrixMalin :

   ```
   set PRIXMALIN_SSL_CERTFILE=C:\chemin\localhost+3.pem
   set PRIXMALIN_SSL_KEYFILE=C:\chemin\localhost+3-key.pem
   lancer.bat
   ```

4. PrixMalin s'ouvre alors en `https://localhost:8000` sur le PC et en `https://192.168.1.10:8000` sur le téléphone (adresse et QR code de la fenêtre noire).

Le certificat racine de mkcert permet de créer des certificats reconnus par vos appareils : ne le donnez à personne.

## Pour les curieux : ce qui protège PrixMalin

- Seules les adresses du PC sont acceptées (localhost, adresses IP, nom du PC, `nom.local`, `*.ts.net`, et `PRIXMALIN_ALLOWED_HOSTS`) : un site web ne peut pas joindre PrixMalin par un nom à lui.
- Les modifications (liste, réglages...) ne sont acceptées que depuis les pages de PrixMalin lui-même.
- Hors du PC, chaque demande à PrixMalin doit porter le cookie obtenu avec le code d'accès (`HttpOnly`, `SameSite=Strict`, valable un an). Le code et la clé de ces cookies sont gardés dans le dossier des données (`acces-telephone.json`), jamais dans une sauvegarde, un journal ou un rapport de diagnostic.
