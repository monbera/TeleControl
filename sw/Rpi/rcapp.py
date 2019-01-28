#! /usr/bin/env python
#-------------------------------------------------------------------------------
# Name:        Remote Control Receiver 
# Purpose:     Receiving remote control commands, controlling 
#              seros, H-Bridges and digital outputs using a PCA9685 board     
# Author:      Bernd Hinze
#
# Created:     28.01.2019
# Copyright:   (c) Bernd Hinze 2019
# Licence:     MIT see https://opensource.org/licenses/MIT
# -------------------------------------------------------------------------------
from __future__ import division, print_function
import socket
import time
import os
import fcntl
import struct
from threading import Thread
from pca9685 import PCA9685   # PWM Board Package


class Utility(): 
    def get_ip_address(ifname):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            return socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915,
                struct.pack('256s', ifname[:15]))[20:24])
        except:
            return "127.0.0.0"
             
    def get_bc_address(ifname):
        ip = Utility.get_ip_address(ifname).split('.')
        bcip = ip[0] + '.' + ip[1] + '.' + ip[2] + '.' + '255'
        return bcip
           
    get_ip_address = staticmethod(get_ip_address)
    get_bc_address = staticmethod(get_bc_address)


class PWM_Controller(PCA9685):
    def __init__(self, i_min, i_max, freq, L298s = [], Dios=[], Inv = []):
        PCA9685.__init__(self)
        self.freq = freq
        self.set_pwm_freq(self.freq) 
        self.imp_tab = []
        self.invert_input = []
        self.i_min = i_min
        self.i_max = i_max
        self.L298Chs = L298s
        self.Dios = Dios
        self.Inv = Inv
        self.servo_min =  int(round(((self.i_min * self.freq) / 1000) * 4095))
        self.servo_max =  int(round(((self.i_max * self.freq) / 1000) * 4095))  
        self.diff = self.servo_max - self.servo_min        
        self.calc_puls_table()
        # update of pulstable for LM298 purposes
        i = 0
        for i in range(len(self.L298Chs)):
            if (i % 3 == 0):
                self.calc_puls_table_L298(self.L298Chs[i])                   
 
        self.create_invert_table()
        self.rtime = time.time()
        
    def get_rtime(self):
        return self.rtime

    def create_invert_table (self):
        ri = 254
        for i in range (255):
            self.invert_input.append(ri - i )
    
    def calc_puls_table_L298 (self, chan):
        """ call after 'calc_puls_table'
        """
        tab  = []
        diff =  4095
        for i in range (255):
            if (i <= 127):
                 tab.append(int(diff -(diff * i/127)))
            else: 
                 tab.append(int(diff * (i-127)/127))
        self.imp_tab[chan] = tab
        
    def calc_puls_table (self):
        """ 
        """
        ttab = []
        for i in range(255):  
            ttab.append(int((self.diff * i/254) + self.servo_min)) 
        for c in range (16):
            self.imp_tab.append(ttab)   
            
    def trimm_chan (self, chan, trimm):
        ''' trim is a value in range 0 .. 50 and shifts the 
            table values of ((trim-25)/254 * self.diff)    
        '''
        if (chan in self.L298Chs):
            pass
        else:         
            korr = (trimm - 25)/254 * self.diff
            #print 'korr', korr
            if  (trimm < 51):
                for i in range(254):
                    self.imp_tab[chan][i] = \
                        int(((self.diff * i/254) + self.servo_min) + korr)  
        
    def fail_safe(self):
        for i in range(16):
            if (i in self.Dios):
                if (i in self.Inv):
                    self.update_Dio(i, 254)       
                else:
                    self.update_Dio(i, 0)
            elif (i in self.L298Chs): 
                idx = self.L298Chs.index(i)
                if (idx % 3) == 0:
                    self.update_L298(i, 127)   # powerless
            else: 
                self.update_Servo(i, 127)  # center position
                               
    def update_L298(self, chan, remote_inp):
        self.set_pwm(chan, 0, self.imp_tab[chan][remote_inp])
        dio = self.L298Chs.index(chan)
        if (remote_inp < 127):          
            self.set_dio(self.L298Chs[dio+1], 0)
            self.set_dio(self.L298Chs[dio+2], 1)  
        elif (remote_inp > 127):
            self.set_dio(self.L298Chs[dio+1], 1)
            self.set_dio(self.L298Chs[dio+2], 0)  
        else: 
            self.set_dio(self.L298Chs[dio+1], 0)
            self.set_dio(self.L298Chs[dio+2], 0)  

    def update_Dio(self, chan, remote_inp): 
        self.set_dio(chan, remote_inp)
            
    def update_Servo(self, chan, remote_inp):
        self.set_pwm(chan, 0, self.imp_tab[chan][remote_inp])

    def update_ch(self, chan, remote_inp):
        inp = remote_inp    
        if (chan in self.Inv):
            inp = self.invert_input[remote_inp]               
        if (chan in self.Dios): 
            self.update_Dio(chan, inp)
        elif (chan in self.L298Chs):    
            self.update_L298(chan, inp)
        else: 
            self.update_Servo(chan, inp)
            
    def update(self, msg):
        ''' calling the boad update function 
            with extracted channel and set value
        '''
        self.rtime = time.time()
        i = 0 
        for i in range (len(msg)//3) :
            hdr = msg[i*3 + 0]      
            ch = msg[i*3 + 1]
            val = msg[i*3 + 2]
            if (hdr == 127):
                self.trimm_chan(ch, val)
            else:
                print (ch, val)   
                self.update_ch(ch, val)

class Observer(Thread):
    def __init__(self, SC, tel_time_out, ID):
        Thread.__init__(self)
        self.SC = SC
        self.tout = tel_time_out
        self.ID = ID
        self.start()

    def run(self):
        ''' checks whether a timeout without telegramm receiving 
            happens, if so an system action can be places here  
        '''
        while True:
            if ((time.time() - self.SC.get_rtime()) > self.tout):
                self.SC.fail_safe()
                time.sleep(1)
                print ('Beenden' + str(os.getpid()))
                os.system("sudo kill " + str(os.getpid()))
                # os.system("sudo shutdown ")
            time.sleep(1)  

 
class UDP_Client(Thread):
    """  simple UDP receiver with telegramm decoding""" 
    def __init__(self, controller, IP, port_tx, port_rx, tbroadcast, ID):
        Thread.__init__(self)
        self.controller = controller
        self.ID = ID
        self.tbc = tbroadcast
        self.port_tx = port_tx
        self.port_rx = port_rx
        self.bc_address = (Utility.get_bc_address('wlan0'), self.port_tx)
        self.bc_data = self.ID + '@' + Utility.get_ip_address('wlan0')
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.client_address = (IP, port_rx)
        self.sock.bind(self.client_address)
        self.msCyclTime = int(round(time.time() * 1000))
        for i in range(self.tbc):
             sent = self.sock.sendto(self.bc_data, self.bc_address)        
             time.sleep(0.1)                       
        self.start()          

    def run(self):  
        print ("Start UDP")
        while True:
            if ((int(round(time.time() * 1000)) - self.msCyclTime) > 1000):
                self.msCyclTime = int(round(time.time() * 1000))
                try: 
                    sent = self.sock.sendto(self.bc_data, self.bc_address)
                    print ('broadcast', self.bc_data)                   
                except:
                    print ("Network not available - shutdown")
                    os.system("sudo shutdown ")
            data , address = self.sock.recvfrom(1024)
            print (data)
            if data:
                try:
                    msg = self.decode_Tel(data) 
                    self.update_Controller(msg)                  
                except:
                    msg = [] 
                    
 
    def decode_Tel(self, input):
        ''' input: string coded telegramm
            return: list of repeated channel data [hdr, chn, val, ....]
        '''
        data = []
        l = len(input)
        i = 0
        for i in range (0, l-5 , 6):
            data.append(((ord(input[i]) & 0x0F) << 4) + (ord(input[i+1]) & 0x0F)) 
            data.append(((ord(input[i+2]) & 0x0F) << 4) + (ord(input[i+3]) & 0x0F)) 
            data.append(((ord(input[i+4]) & 0x0F) << 4) + (ord(input[i+5]) & 0x0F))       
        return data 

    def update_Controller(self, msg):
        self.controller.update(msg)
        

def main():
    time.sleep(10) 
    L298Channels = [0, 1, 2]
    DIOs = [3]
    Inverted = []  
    SC = PWM_Controller(1.0, 2.0, 50, L298Channels, DIOs, Inverted)
    SC.fail_safe()
    S = UDP_Client(SC,'', 6000, 6100, 10, "RC#001")
    O = Observer(SC, 30.0, "RC#001")

if __name__ == '__main__':
    main()