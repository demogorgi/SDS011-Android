# SDS011-Android
This Repo contains a manual and python3 code to set up a SDS011 particulate sensor connected with the HC-06 bluetooth module under Android. The measurements are presented in a QPython 3L WebApp using the Python web framework bottle. It is heavily influenced by https://github.com/optiprime/Feinstaubsensor However optiprimes code is not working under python3.x. The urge to get the setup running with Qpython 3L led to this repository.

1. Install QPython 3L from Google Play https://play.google.com/store/apps/details?id=org.qpython.qpy3&gl=DE
2. Open In QPython 3L-App, choose console and execute
``import pip; pip.main(['install', 'bottle'])``
3. Save the repository https://github.com/demogorgi/SDS011-Android/archive/refs/heads/main.zip under /storage/emulated/0/qpython/ and unzip it
4. Assemble the dust sensor as shown in the image below
![Wiring](https://github.com/demogorgi/SDS011-Android/blob/main/Wiring.jpg)
and connect the USB plug with a power bank
5. In Qpython 3L choose Programs > SDS011-Android > Run
