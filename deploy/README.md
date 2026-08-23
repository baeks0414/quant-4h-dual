# VPS deployment

GitHub Actions was measured firing 34-66 minutes after the 4h bar close, and it
can skip a scheduled run entirely under load. For paper trading that is
harmless. Holding a real position through a skipped run is not, which is the
only reason to move to a VPS. Any 1 vCPU / 1 GB box is ample.

## Setup

```bash
sudo adduser --system --group quant
sudo mkdir -p /opt/quant-4h-dual /var/log/quant4h
sudo chown -R quant:quant /opt/quant-4h-dual /var/log/quant4h

sudo -u quant git clone https://github.com/baeks0414/quant-4h-dual /opt/quant-4h-dual
cd /opt/quant-4h-dual
sudo -u quant python3 -m venv .venv
sudo -u quant .venv/bin/pip install -e . --quiet

sudo cp deploy/quant4h.env.example /etc/quant4h.env
sudo chmod 600 /etc/quant4h.env
sudo nano /etc/quant4h.env          # fill in keys, keep DRY_RUN=1

sudo cp deploy/quant4h.service deploy/quant4h.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quant4h.timer
```

## Going live

1. `sudo systemctl start quant4h.service` and read `/var/log/quant4h/run.log`.
   It must print `mode=DRY RUN` and a sensible order plan.
2. Let the timer run several bars in dry mode. Confirm the plan matches the
   paper account's positions each time.
3. Only then set `DRY_RUN=0` in `/etc/quant4h.env` and restart the timer.

## Checks

```bash
systemctl list-timers quant4h.timer      # next fire time
journalctl -u quant4h.service -n 50      # last run
tail -f /var/log/quant4h/run.log
cat /opt/quant-4h-dual/results/live_real/state.json
```

## Kill switch

Trading halts permanently once the wallet falls `KILL_DRAWDOWN` below the
baseline recorded on the first run. It latches: `killed_at` is written to
`results/live_real/state.json` and the runner refuses to trade until you delete
that field yourself. It will not resume because the balance recovered.

To stop everything immediately:

```bash
sudo systemctl stop quant4h.timer
```

Existing positions are NOT closed by stopping the timer. Close them manually on
Binance if that is what you want.

## API key

Futures trading permission only. Withdrawals disabled. IP whitelist set to this
VPS. The key is read from `/etc/quant4h.env`, which is root-owned and 600, and
is never written to logs or committed.
