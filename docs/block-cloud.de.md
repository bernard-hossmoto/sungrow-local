# Den Wechselrichter von der Cloud trennen

[English version](block-cloud.md)

Läuft sungrow-local, braucht der Wechselrichter die iSolarCloud nicht mehr, damit du
siehst, was er tut. Man kann den WiNet-S vom Internet trennen und nur für ein
Firmware-Update kurz wieder freigeben. Modbus im eigenen Netz läuft weiter, das verlässt
das Haus ja nie.

Die Cloud auszusperren ist aber nur die halbe Sache. Der Modbus-Port, den sungrow-local
braucht, hat keine Anmeldung. Der Dongle gehört deshalb auch vom übrigen Heimnetz
abgeschirmt. Beides steht unten.

> An der getesteten Anlage läuft das Dashboard, die Sperre selbst ist vorbereitet, aber
> noch nicht aktiv. Die Schritte unten sind der Plan, kein Langzeitbericht. Rückmeldungen
> sind willkommen.

## Vor dem Sperren

- **Zuerst die Firmware aktualisieren.** WiNet-S-Firmware bis `WINET-SV200.001.00.P027`
  hat veröffentlichte Schwachstellen (fest eingebaute Zugangsdaten, keine Prüfung der
  Firmware, Pufferüberläufe; zum Beispiel
  [CVE-2024-50692](https://en.sungrowpower.com/security-notice-detail-2/6136)). Ein Dongle,
  der vor dem Update gesperrt wird, bleibt für jeden im Heimnetz angreifbar. Den
  Firmwarestand in der App prüfen und das Update laufen lassen, solange er noch Internet hat.
- **Das Admin-Passwort** der lokalen Weboberfläche des Dongles ändern (siehe
  [setup-winet.de.md](setup-winet.de.md), Weg B). Diese Oberfläche bleibt aus dem Heimnetz
  erreichbar.
- **Netzbetreiber.** In manchen Ländern verlangt der Netzbetreiber, dass die Anlage über
  die Hersteller-Cloud fernsteuerbar ist oder ihre Einspeisung begrenzt. Zuerst die
  Bedingungen des eigenen Netzanschlusses prüfen.
- **Installateur.** Dem Installateur Bescheid geben. Sein Fernzugriff über die Cloud geht
  dann nicht mehr, und er soll nicht nach einem Fehler suchen, der nur deine Firewall ist.
- **Was wegfällt:** iSolarCloud-App und Webportal, Fernwartung, automatische
  Firmware-Updates und womöglich die Zeitsynchronisierung des Wechselrichters (siehe unten).

## WiNet-S abschotten

**Port 502 hat keine Anmeldung.** Alles, was ihn erreicht, kann den Wechselrichter
auslesen, und man muss davon ausgehen, dass es auch Einstellungen schreiben kann:
Sungrow-SH-Wechselrichter nehmen über dieselbe Schnittstelle Speichermodus, Zwangsladung
und -entladung, Einspeisegrenze sowie Start und Stopp an. Genau so steuern evcc und die
Home-Assistant-Integration den Speicher. sungrow-local liest nur, kann den Port aber nicht
schützen. Ein gekapertes Handy, ein Fernseher, eine smarte Steckdose oder der Laptop eines
Gastes im selben Netz kann direkt mit dem Wechselrichter reden.

Ziel ist genau ein erlaubter Weg, **Rechner mit sungrow-local → WiNet-S, TCP 502**, und
sonst nichts zum oder vom Dongle: kein Internet, kein Zugriff anderer Geräte auf seine
Weboberfläche (TCP 80 und 443), keine Weiterleitung irgendwohin.

### Empfohlen: ein eigenes Netzsegment

Den WiNet-S in ein eigenes Netz stellen: ein VLAN, ein eigenes "IoT"-Netz oder eine
eigene Firewall-Zone. Dann sieht der Router jedes Paket vom und zum Dongle und kann es
filtern.

**OpenWrt.** Angenommen, der Dongle hängt in einem eigenen Netz namens `sungrow` (VLAN,
eigener Port oder eigenes WLAN), der Rechner mit dem Dashboard hat `192.168.1.10`, der
Dongle `192.168.20.2`:

```sh
# Zone für den Dongle: kein Zugriff auf Router, Internet oder andere Zonen
uci set firewall.sungrow=zone
uci set firewall.sungrow.name='sungrow'
uci set firewall.sungrow.network='sungrow'
uci set firewall.sungrow.input='REJECT'
uci set firewall.sungrow.output='ACCEPT'
uci set firewall.sungrow.forward='REJECT'

# DHCP vom Router braucht der Dongle trotzdem
uci set firewall.sungrow_dhcp=rule
uci set firewall.sungrow_dhcp.name='Sungrow WiNet-S: DHCP'
uci set firewall.sungrow_dhcp.src='sungrow'
uci set firewall.sungrow_dhcp.proto='udp'
uci set firewall.sungrow_dhcp.dest_port='67-68'
uci set firewall.sungrow_dhcp.target='ACCEPT'

# nur der Dashboard-Rechner darf an Modbus
uci set firewall.sungrow_modbus=rule
uci set firewall.sungrow_modbus.name='sungrow-local zu WiNet-S Modbus'
uci set firewall.sungrow_modbus.src='lan'
uci set firewall.sungrow_modbus.src_ip='192.168.1.10'
uci set firewall.sungrow_modbus.dest='sungrow'
uci set firewall.sungrow_modbus.dest_ip='192.168.20.2'
uci set firewall.sungrow_modbus.proto='tcp'
uci set firewall.sungrow_modbus.dest_port='502'
uci set firewall.sungrow_modbus.target='ACCEPT'

uci commit firewall && /etc/init.d/firewall reload
```

Kein `forwarding` von `sungrow` nach `wan` oder von `lan` nach `sungrow` anlegen. Weil
der Dongle auch den DNS des Routers nicht nutzen darf, bleibt ihm kein langsamer
Nebenkanal über Namensabfragen. Für ein Firmware-Update vorübergehend ein Forwarding
`sungrow → wan` anlegen und danach wieder entfernen (und für diese Zeit DNS, UDP und TCP
53, aus `sungrow` erlauben).

**OPNsense / pfSense.** Auf der Schnittstelle des Dongle-VLANs eine **Block**-Regel mit
Quelle = Dongle und Ziel = beliebig. Auf der LAN-Schnittstelle eine **Pass**-Regel mit
Quelle = Dashboard-Rechner, Ziel = Dongle, TCP-Port 502, darunter eine **Block**-Regel mit
Ziel = Netz des Dongles. Für ein Update eine vorübergehende Pass-Regel vom Dongle ins
Internet über die Block-Regel schieben.

### Ohne VLANs

In einem flachen Heimnetz läuft der Verkehr zwischen zwei Geräten über den Switch, nicht
durch die Firewall des Routers. Der Router kann den Dongle dann vom **Internet** trennen,
aber nicht verhindern, dass andere Geräte im Heimnetz Port 502 erreichen. Was trotzdem
hilft:

- Den Internetzugang des Dongles sperren (nächster Abschnitt).
- WLAN-Client-Isolation, wenn Dongle und die übrigen Geräte im WLAN sind und der Router
  das anbietet.
- Die Grenze ehrlich sehen: In einem flachen Netz erreicht jedes Gerät im Haus den
  Wechselrichter. Wem das wichtig ist, der gibt dem Dongle ein eigenes Netz.

## Nur das Internet sperren

Die Idee ist immer dieselbe: Der WiNet-S darf ins Heimnetz, aber nicht ins Internet. Zuerst
eine feste Adresse vergeben (DHCP-Reservierung), dann eine Regel für ihn anlegen.

### Üblicher Heimrouter

Viele Router haben je Gerät einen Schalter "Internetzugang sperren", oft unter
Kindersicherung oder Zugangsprofilen. Dort den WiNet-S auswählen. Das Heimnetz geht weiter.

### OpenWrt (uci)

Den Dongle an seiner **MAC-Adresse** erkennen, nicht an der IP: Ein Gerät, das seine
Adresse selbst ändert oder eine neue Lease bekommt, fiele sonst aus der Regel. Die MAC
durch die des eigenen WiNet-S ersetzen:

```sh
uci set firewall.sungrow_block=rule
uci set firewall.sungrow_block.name='Sungrow WiNet-S: kein Internet'
uci set firewall.sungrow_block.src='lan'
uci set firewall.sungrow_block.src_mac='AC:19:9F:00:00:00'
uci set firewall.sungrow_block.dest='wan'
uci set firewall.sungrow_block.proto='all'
uci set firewall.sungrow_block.target='REJECT'
uci commit firewall && /etc/init.d/firewall reload
```

Auch eine MAC-Adresse kann das Gerät selbst ändern. Wer der Firmware des Dongles nicht
traut, hat mit dem eigenen Netz oben die einzige Regel, die nicht auf die Mitarbeit des
Dongles angewiesen ist. Den DNS-Resolver des Routers kann der Dongle außerdem weiter
fragen; dagegen hilft eine Regel, die UDP und TCP Port 53 vom Dongle zum Router abweist
(`src lan`, `src_mac` wie oben, kein `dest`, `dest_port 53`, `target REJECT`).

Für ein Update öffnen und danach wieder schließen:

```sh
uci set firewall.sungrow_block.enabled='0' && uci commit firewall && /etc/init.d/firewall reload
uci set firewall.sungrow_block.enabled='1' && uci commit firewall && /etc/init.d/firewall reload
```

### OPNsense / pfSense

Auf der LAN-Schnittstelle eine **Block**-Regel anlegen mit Quelle = Adresse des WiNet-S
(oder ein Alias mit seiner MAC) und Ziel = *nicht* LAN-Netz, und sie über die
Standardregel "LAN darf alles" schieben. Für ein Update die Regel deaktivieren.

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
- Von einem **anderen** Gerät im Heimnetz (nicht dem Dashboard-Rechner) muss
  `nc -z -w 3 <ip-des-winet> 502` scheitern. Klappt es, erreichen andere Geräte den
  Modbus-Port noch.
