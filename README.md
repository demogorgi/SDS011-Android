# SDS011-Android
This Repo contains a manual and python3 code to set up a SDS011 particulate sensor connected with the HC-06 bluetooth module under Android. The measurements are presented in a QPython 3L WebApp using the Python web framework bottle.

<p align="center">It is heavily influenced by<br>https://github.com/optiprime/Feinstaubsensor</p>

However optiprimes code is not working under python3.x. The urge to get the setup running with QPython 3L led to this repository.

1. Install QPython 3L from Google Play https://play.google.com/store/apps/details?id=org.qpython.qpy3&gl=DE
2. Open In QPython 3L-App, choose console and execute
``import pip; pip.main(['install', 'bottle'])``
3. Download the repository https://github.com/demogorgi/SDS011-Android/archive/refs/heads/main.zip and unzip it
4. Copy the folder SDS011-Android-main (deepest level) to /storage/emulated/0/qpython/projects3 (Interner Speicher > qpython > projects3)
5. Assemble the dust sensor as shown in the image below and connect the USB plug with a power bank
   <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Wiring.jpg" width=30% alt=Wiring"></div>
7. In Qpython 3L choose Programs > projects > SDS011-Android-main > Run
8. Should look like this then: <div><img src="https://github.com/demogorgi/SDS011-Android/blob/main/Screenshot_QPython%203L.jpg" width=20% alt="Screenshot WebApp"></div>
9. In the output directory you will find two kml-files, a csv-file and a log-file
    * The csv file's format ist ``timestamp;pm_10;pm2.5;lat;lon``
    * The kml-files contain a pm_10 and pm_2.5 "trajectory" that can be viewed in GoogleEarth (make sure to press the "Stop"-Button in the WebApp to get vaild kml files)
    * The logfile contains some logging
