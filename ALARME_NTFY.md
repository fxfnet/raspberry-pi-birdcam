# Alarme ntfy de la birdcam

Un veilleur tourne sur **macaron** (toujours allumé, hors du Pi) et prévient par ntfy.sh quand la birdcam ne répond plus.

| Pièce | Où | Rôle |
|---|---|---|
| `scripts/ntfy/surveillant_birdcam.py` | macaron, `~/birdcam/` | Une fois par minute, `GET /static/mesange.svg` sur la galerie du Pi (port 5000). Alerte après 5 échecs de suite, rappel toutes les 6 h, message de retour après 2 succès. Une panne qui revient moins de 30 min après un retour à la normale est déclarée mais annoncée seulement si elle dure (comme D56 de spirubot). Un envoi raté est repris avec une attente croissante (1, 2, 4 ... 30 min) |
| ntfy.sh | Internet | Reçoit et pousse vers l'iPhone |

**Ce que cela détecte** : Pi éteint ou planté, réseau coupé, service `birdcam-gallery` arrêté.

**Ce que cela ne détecte pas** :
- une galerie dont la page d'accueil est en erreur ou dont la clé USB des photos est morte : la page statique de la carte SD répond quand même ;
- la capture (`birdcam.service`) arrêtée alors que la galerie répond ;
- la galerie d'administration, le disque, la sauvegarde vers macaron ;
- une galerie absente 4 minutes sur 5 (le compte d'échecs repart à zéro au premier succès) ;
- une panne plus courte que 5 minutes ;
- un « Rétabli » dont la réponse de ntfy s'est perdue : il est repris, FX peut le recevoir deux fois ; si le Pi retombe aussitôt, une nouvelle alerte part (cas traité) ;
- Internet coupé chez FX ou macaron éteint : plus personne n'envoie.

Le sujet ntfy est secret (`birdcam-` suivi de 16 caractères au hasard, jamais dans le dépôt) et distinct de celui de spirubot. **Quota du service gratuit : 250 messages par jour et par adresse IP, partagé avec le service d'alarmes et le veilleur de spirubot**, qui sortent par la même box ; des dépassements répétés peuvent valoir un bannissement temporaire. Une galerie qui oscille (Pi qui redémarre en boucle) produit au plus environ 90 messages par jour grâce à la retenue de 30 min ; plus (jusqu'à 170 mesurés en simulation) si les réponses de ntfy se perdent souvent, parce que les envois sont alors repris ; une panne continue en produit 4 (alerte puis rappels toutes les 6 h). Aucun plafond ne couvre ensemble la birdcam et spirubot : les deux peuvent dépasser les 250 messages par jour en cas de pannes simultanées.

## Installation (macaron)

Depuis le Mac de travail, dans une copie du dépôt (les fichiers ne sont pas sur macaron) :

```
ssh macaron@192.168.1.177 'mkdir -p ~/birdcam ~/Library/LaunchAgents'
scp scripts/ntfy/surveillant_birdcam.py macaron@192.168.1.177:birdcam/
scp scripts/ntfy/fr.faucher.birdcam-veilleur.plist macaron@192.168.1.177:Library/LaunchAgents/
```

(Si macaron refuse la clé du Mac de travail, utiliser une clé dédiée ou copier les fichiers autrement.)

Puis sur macaron :

```
mkdir -p ~/Library/Logs && install -d -m 700 ~/.config/birdcam
install -m 600 /dev/null ~/.config/birdcam/veilleur.json
# contenu : {"gallery": "http://192.168.1.40:5000", "url": "https://ntfy.sh", "topic": "birdcam-XXXXXXXXXXXXXXXX"}
/usr/bin/python3 ~/birdcam/surveillant_birdcam.py; echo "sortie=$?"            # 0 attendu ; 2 = configuration invalide
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/fr.faucher.birdcam-veilleur.plist
launchctl print gui/$(id -u)/fr.faucher.birdcam-veilleur | head -5   # le veilleur est chargé
```

Vérifier ensuite, deux minutes plus tard, que `~/.local/state/birdcam/veilleur.json` existe et que `oks` augmente. Mise à jour du script : `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/fr.faucher.birdcam-veilleur.plist`, copier, puis `bootstrap` de nouveau.

L'adresse du Pi est son IP (`192.168.1.40`) : `oaso.local` ne se résout pas toujours depuis macaron. Si le Pi change d'IP, modifier `gallery` dans `veilleur.json`.

**Réserves à vérifier sur macaron** : un LaunchAgent ne tourne que si l'utilisateur `macaron` a une session ouverte (après une coupure de courant, sans connexion automatique, le veilleur ne repart pas) ; la confidentialité « Réseau local » de macOS peut bloquer la sonde lancée par launchd.

iPhone : application ntfy, s'abonner au sujet sur le serveur `ntfy.sh`.

## Essai et retour arrière

- Tests sans réseau : `python3 scripts/test_surveillant_birdcam.py`.
- Essai réel : arrêter la galerie (`ssh birdcam 'sudo systemctl stop birdcam-gallery'`), attendre 6 minutes, puis `start`. Une intervention prévue sur le Pi déclenche l'alerte : arrêter d'abord le veilleur (`launchctl bootout` comme ci-dessus), et le relancer après en supprimant `~/.local/state/birdcam/` si l'intervention a duré plus de quelques minutes.
- Retour arrière : `launchctl bootout` ; supprimer `~/birdcam/`, `~/.config/birdcam/` et `~/.local/state/birdcam/`. `~/birdcam_backups/` (sauvegardes des photos) n'est pas touché.
