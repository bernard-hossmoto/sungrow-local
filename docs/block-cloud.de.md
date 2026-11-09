# Den Wechselrichter von der Cloud trennen

[English version](block-cloud.md)

Läuft sungrow-local, braucht der Wechselrichter die iSolarCloud nicht mehr, damit du
siehst, was er tut. Man kann den WiNet-S vom Internet trennen und nur für ein
Firmware-Update kurz wieder freigeben. Modbus im eigenen Netz läuft weiter, das verlässt
das Haus ja nie.

> An der getesteten Anlage läuft das Dashboard, die Sperre selbst ist vorbereitet, aber
> noch nicht aktiv. Die Schritte unten sind der Plan, kein Langzeitbericht. Rückmeldungen
> sind willkommen.

## Vor dem Sperren

- **Netzbetreiber.** In manchen Ländern verlangt der Netzbetreiber, dass die Anlage über
  die Hersteller-Cloud fernsteuerbar ist oder ihre Einspeisung begrenzt. Zuerst die
  Bedingungen des eigenen Netzanschlusses prüfen.
- **Installateur.** Dem Installateur Bescheid geben. Sein Fernzugriff über die Cloud geht
  dann nicht mehr, und er soll nicht nach einem Fehler suchen, der nur deine Firewall ist.
- **Was wegfällt:** iSolarCloud-App und Webportal, Fernwartung, automatische
  Firmware-Updates und womöglich die Zeitsynchronisierung des Wechselrichters (siehe unten).

## So wird gesperrt

Die Idee ist immer dieselbe: Der WiNet-S darf ins Heimnetz, aber nicht ins Internet. Zuerst
eine feste Adresse vergeben (DHCP-Reservierung), dann eine Regel für diese Adresse anlegen.

### Üblicher Heimrouter

Viele Router haben je Gerät einen Schalter "Internetzugang sperren", oft unter
Kindersicherung oder Zugangsprofilen. Dort den WiNet-S auswählen. Das Heimnetz geht weiter.

### OpenWrt (uci)

Eine Regel mit Namen lässt sich später leicht ein- und ausschalten. Die Adresse durch die
des eigenen WiNet-S ersetzen:

```sh
uci set firewall.sungrow_block=rule
uci set firewall.sungrow_block.name='Sungrow WiNet-S: kein Internet'
uci set firewall.sungrow_block.src='lan'
uci set firewall.sungrow_block.src_ip='192.168.1.100'
uci set firewall.sungrow_block.dest='wan'
uci set firewall.sungrow_block.proto='all'
uci set firewall.sungrow_block.target='REJECT'
uci commit firewall && /etc/init.d/firewall reload
```

Für ein Update öffnen und danach wieder schließen:

```sh
uci set firewall.sungrow_block.enabled='0' && uci commit firewall && /etc/init.d/firewall reload
uci set firewall.sungrow_block.enabled='1' && uci commit firewall && /etc/init.d/firewall reload
```

### OPNsense / pfSense

Auf der LAN-Schnittstelle eine **Block**-Regel anlegen mit Quelle = Adresse des WiNet-S und
Ziel = *nicht* LAN-Netz, und sie über die Standardregel "LAN darf alles" schieben. Für ein
Update die Regel deaktivieren.

## Firmware-Updates

1. Sperrregel ausschalten.
2. Warten, bis die App die Anlage wieder online zeigt, dann das Update starten (oder laufen
   lassen).
3. Regel wieder einschalten.

## Die Uhr im Auge behalten

Die Tageszähler (heutige Erzeugung, Einspeisung und so weiter) springen um Mitternacht
**nach der Uhr des Wechselrichters** auf 0. Wie der Wechselrichter ohne Cloud seine Zeit
stellt, haben wir nicht geprüft. Nach dem Sperren ein paar Tage beobachten, ob die
Tageswerte weiterhin um Mitternacht bei 0 beginnen. Laufen sie davon, den WiNet-S ab und zu
kurz ins Internet lassen oder nur die Zeitsynchronisierung erlauben (NTP, UDP-Port 123).

## Prüfen, ob es wirkt

- Das Protokoll von Router oder Firewall zeigt abgewiesene Verbindungen vom WiNet-S.
- Nach einer Weile zeigt die iSolarCloud-App die Anlage offline.
- sungrow-local zeigt weiter Live-Werte.
