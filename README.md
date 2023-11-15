# SDS011-Android
This Repo contains a manual and python3 code to set up a SDS011 particulate sensor connected with the HC-06 bluetooth module under Android. The measurements are presented in a QPython 3L WebApp using the Python web framework bottle. It is heavily influenced by https://github.com/optiprime/Feinstaubsensor However optiprimes code is not working under python3.x. The urge to get the setup running with Qpython 3L led to this repository.

1. In QPython 3L choose console and type
import pip
pip.main(['install', 'bottle'])
pip.main(['install', 'matplotlib'])
2. Save the repository under /storage/emulated/0/qpython/
3. Assemble the dust sensor as shown in ... and connect it with a power bank
4. In Qpython 3L choose SD... and run
