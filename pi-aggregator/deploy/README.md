# Déploiement sur le Raspberry Pi (systemd)

Met `pi-aggregator` en service permanent : il démarre au boot, redémarre en cas
de crash, et expose `GET /dashboard` en HTTP local pour l'ESP32.

Hypothèses de cette procédure (voir [`install.sh`](install.sh) pour les changer
via variables d'environnement) :

- le service tourne sous l'utilisateur **`pi`** ;
- depuis le checkout du repo dans le **home** (ex. `/home/pi/ESP32-Dashboard`) ;
- config + secrets dans **`/etc/pi-aggregator/config.toml`** (hors du repo).

## Prérequis

- Raspberry Pi OS avec **Python ≥ 3.11** (`python3 --version`).
- `git`, `sudo`, et `python3-venv` (`sudo apt install -y git python3-venv`).

## Installation

```bash
# 1. Récupérer le code (si pas déjà fait)
git clone https://github.com/gurnari/ESP32-Dashboard.git ~/ESP32-Dashboard
cd ~/ESP32-Dashboard

# 2. Installer le service (venv, dépendances, config, unit systemd)
./pi-aggregator/deploy/install.sh
```

Le script est **idempotent** : crée le venv, installe les dépendances, dépose
`/etc/pi-aggregator/config.toml` (depuis `config.example.toml`, **sans écraser**
un fichier existant), génère et active le unit `pi-aggregator.service`.

## Configuration

À la première install, le service est *enabled* mais **pas démarré** : il faut
d'abord renseigner la config.

```bash
sudo nano /etc/pi-aggregator/config.toml
```

- `[weather]` : `latitude` / `longitude` (et `days`, 1 à 7).
- `[tracking]` : `api_key` PKGE (laisser vide → clé `tracking` omise du JSON).
- `[claude]` : `admin_api_key` Anthropic (laisser vide → clé `claude` omise ;
  l'Admin API exige une **organisation Console**).
- `[server]` : `port` (défaut `8080`).

Puis :

```bash
sudo systemctl start pi-aggregator
```

> Le chemin du `layout.json` servi est réglé en absolu vers le repo
> (`~/ESP32-Dashboard/pi-aggregator/layout.json`) : tu peux l'éditer sur place
> pour changer la disposition des widgets sans reflasher l'ESP32. Pour le
> découpler complètement de git, copie-le dans `/etc/pi-aggregator/` et mets à
> jour `file = ...` dans la config.

## Vérification

```bash
systemctl status pi-aggregator          # doit être "active (running)"
curl -s http://localhost:8080/healthz | python3 -m json.tool
curl -s http://localhost:8080/dashboard | python3 -m json.tool
```

Depuis un autre appareil du LAN, remplace `localhost` par l'IP du Pi : c'est
cette adresse (`IP:8080`) à saisir dans le portail de config de l'ESP32.

## Mise à jour

```bash
cd ~/ESP32-Dashboard && git pull
./pi-aggregator/deploy/install.sh        # réinstalle deps + unit, redémarre
```

## Exploitation

```bash
journalctl -u pi-aggregator -f           # logs en direct
sudo systemctl restart pi-aggregator     # redémarrer
sudo systemctl disable --now pi-aggregator   # arrêter et désactiver
```

## Désinstallation

```bash
sudo systemctl disable --now pi-aggregator
sudo rm /etc/systemd/system/pi-aggregator.service
sudo systemctl daemon-reload
# config conservée : sudo rm -rf /etc/pi-aggregator
```
