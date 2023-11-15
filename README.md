# SDS011-Android
This Repo contains a manual and python3 code to set up a SDS011 particulate sensor connected with the HC-06 bluetooth module under Android. The measurements are presented in a QPython 3L WebApp using the Python web framework bottle. It is heavily influenced by https://github.com/optiprime/Feinstaubsensor However optiprimes code is not working under python3.x. The urge to get the setup running with Qpython 3L led to this repository.

1. Install QPython 3L from Google Play https://play.google.com/store/apps/details?id=org.qpython.qpy3&gl=DE
2. Open In QPython 3L-App, choose console and execute
``import pip; pip.main(['install', 'bottle'])``
3. Download the repository https://github.com/demogorgi/SDS011-Android/archive/refs/heads/main.zip and unzip it
4. Copy the folder SDS011-Android-main (deepest level) to /storage/emulated/0/qpython/projects3 (Interner Speicher > qpython > projects3)
5. Assemble the dust sensor as shown in the image below and connect the USB plug with a power bank
   <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Wiring.jpg" width=50% alt=Wiring"></div>
7. In Qpython 3L choose Programs > projects > SDS011-Android-main > Run
8. Should look like this then: <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Screenshot_QPython%203L.jpg" width=20% alt="Screenshot WebApp"></div>
