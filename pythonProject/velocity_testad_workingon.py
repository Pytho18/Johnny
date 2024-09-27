# Working version
# To DO
# 1) Omega rolling over



import matplotlib.pyplot as plt
import numpy as np
from vicon_dssdk import ViconDataStream
import argparse
import sys
from digi.xbee.devices import XBeeDevice
from digi.xbee.devices import RemoteZigBeeDevice

from digi.xbee.models.address import XBee64BitAddress
from digi.xbee.models.status import NetworkDiscoveryStatus
from digi.xbee.devices import XBeeDevice, RemoteXBeeDevice

from time import time
from threading import Thread, Event
from time import sleep
from threading import Lock
from scipy.signal import buttap, lp2hp_zpk, bilinear_zpk, zpk2tf, butter, filtfilt
import matplotlib.pyplot as plt
import math
from scipy.spatial.transform import Rotation as R
import time

event = Event()
data_lock = Lock()

# TODO: Replace with the serial port where your local module is connected to.
PORT = "COM4"
# TODO: Replace with the baud rate of your local module.
BAUD_RATE = 115200


def callback_discovery_finished(status):
    if status == NetworkDiscoveryStatus.SUCCESS:
        print("  Discovery process finished successfully.")
    else:
        print("  There was an error discovering devices: %s" % status.description)


def cb_network_modified(event_type, reason, node):
    print("  >>>> Network event:")
    print("         Type: %s (%d)" % (event_type.description, event_type.code))
    print("         Reason: %s (%d)" % (reason.description, reason.code))
    if not node:
        return
    print("         Node:")
    print("            %s" % node)


def print_nodes(xb_net):
    print("\n  Current network nodes:\n    ", end='')
    if xb_net.has_devices():
        print("%s" % '\n    '.join(map(str, xb_net.get_devices())))
    else:
        print("None")


def threaded(fn):
    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper


def vicon_init():
    # Initialise Vicon, get initial pose of all available agents
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', nargs='?', help="Host name, in the format of server:port", default="localhost:801")
    args = parser.parse_args()
    client = ViconDataStream.Client()

    print(" Connecting to Vicon host")
    client.Connect(args.host)
    client.EnableSegmentData()

    hasFrame = False
    timeout = 1000

    while not hasFrame:
        print('.')
        try:
            if client.GetFrame():
                hasFrame = True
            timeout = timeout - 1
            if timeout < 0:
                print('Failed to get frame')
                sys.exit()
        except ViconDataStream.DataStreamException as e:
            client.GetFrame()

    client.SetStreamMode(ViconDataStream.Client.StreamMode.EServerPush)
    print('Get Frame Pull', client.GetFrame(), client.GetFrameNumber())
    print('Segments', client.IsSegmentDataEnabled())

    subjectName = client.GetSubjectNames()
    idata = dict()

    print(subjectName)

    for subName in subjectName:
        segmentName = client.GetSegmentNames(subName)
        print(segmentName)
        print(subName)

        print(segmentName, 'has global translation', client.GetSegmentGlobalTranslation(subName, segmentName[0]))
        pos = client.GetSegmentGlobalTranslation(subName, segmentName[0])[0]

        print(segmentName, 'has global rotation( EulerXYZ )',
              client.GetSegmentGlobalRotationEulerXYZ(subName, segmentName[0]))
        rot = client.GetSegmentGlobalRotationEulerXYZ(subName, segmentName[0])[0]
        # data.update({subName: [pos, rot]})

        idata.update({subName: np.array([pos, rot,pos,rot])})

    idata.update({'dt': 0})

    # Start Vicon
    sleep(0.1)
    print(idata)

    print('Vicon Initialised')  # Press Ctrl+F8 to toggle the breakpoint.
    return client, segmentName, subjectName, idata


def get_Vframe(client):
    return client.GetFrame()
def xbee_init(names):
    xbee_network = None

    xbee = XBeeDevice(PORT, BAUD_RATE)

    try:
        xbee.open()
        xbee.set_sync_ops_timeout(1)

        xbee_network = xbee.get_network()
        remote_devicess = []

        for name in names:
            remote_devicess.append(xbee_network.discover_device(name))

        a = list(map(str, remote_devicess))
        b = []

        for i in range(len(a)):
            b.append(a[i][-8:])

        print(remote_devicess)
        print(b)

    finally:
        if xbee_network is not None:
            xbee_network.del_discovery_process_finished_callback(callback_discovery_finished)
            xbee_network.del_network_modified_callback(cb_network_modified)

    return xbee, remote_devicess, b



###### filters
def lowpass_vel_filter(f, m):
    # order 4
    a1 = 0.2998
    a2 = 0.2477
    a3 = 0.2726
    a4 = 0.2471
    a5 = 0.2998

    # order 6
    a1 = 0.02957
    a2 = 0.04844
    a3 = 0.06826
    a4 = 0.07608
    a5 = 0.06826
    a6 = 0.04844
    a7 = 0.02957
    #a1 =  0.1108 # a1 = 0.5873
    #a2 = 0.1371 #a2 = 0.19251
    #a3 = 0.1794 #a3 = 0.333918
    #a4 = 0.1956 #a4 = 0.40417
    #a5 = 0.1794 #a5 = 0.333918
    #a6 = 0.1371 #a6 = 0.19251
    #a7 = 0.1108 #a7 = 0.058623

    # y0 = a1 * m + a2 * f[0,:] + a3 * f[1,:] + a4 * f[2,:] + a5 * f[3,:]
    y0 = a1 * m + a2 * f[0,:] + a3 * f[1,:] + a4 * f[2,:] + a5 * f[3,:] + a6 * f[4,:] + a7 * f[5,:]
    f[5, :] = f[4, :]
    f[4, :] = f[3, :]
    f[3, :] = f[2, :]
    f[2, :] = f[1, :]
    f[1, :] = f[0, :]
    f[0, :] = m
    #print("filtered")
    # print(y0)
    # print(y1)
    # print(y2)
    # print(x0)
    # print(x1)
    # print(x2)
    return y0, f

def derivative_vel_filter(f, m):

    a1 = 0.0292
    a2 = -0.1952
    a3 = 0.2560
    a4 = 0.2219
    a5 = 0
    a6 = -0.2219
    a7 = -0.2560
    a8 = 0.1952
    a9 = -0.0292

    # a1 = -0.124
    # a2 = 0.248
    # a3 = 0.248
    # a4 = 0.248
    # a5 = -0.124

    y0 = 60*(a1 * m + a2 * f[0, :] + a3 * f[1, :] + a4 * f[2, :] + a5 * f[3, :] + a6 * f[4, :] + a7 * f[5, :]  + a8 * f[6,:] + a9 *f[7,:])
    f[7, :] = f[6, :]
    f[6, :] = f[5, :]
    f[5, :] = f[4, :]
    f[4, :] = f[3, :]
    f[3, :] = f[2, :]
    f[2, :] = f[1, :]
    f[1, :] = f[0, :]
    f[0, :] = m
    # print("filtered")
    # print(y0)
    # print(y1)
    # print(y2)
    # print(x0)
    # print(x1)
    # print(x2)
    return y0, f


def om_filter(f, m):
    y1 = f[0, :]
    y2 = f[1, :]
    x00 = m
    x11 = f[2, :]
    x22 = f[3, :]

    a1 = 0
    a2 = 7.8387
    a3 = -7.8387
    b1 = 1.0000
    b2 = - 1.5622
    b3 = 0.6413

    if abs(x00[2] - x11[2]) > 1.5*math.pi:
        if x00[2] > x11[2]:
            x0 = x00 - 2*math.pi
        elif x00[2] < x11[2]:
            x0 = x00 + 2 * math.pi
    else:
        x0 = x00

    if abs(x11[2] - x22[2]) > 1.5*math.pi:
        if x11[2] > x22[2]:
            x1 = x11 - 2 * math.pi
        elif x11[2] < x22[2]:
            x1 = x11 + 2 * math.pi
    else:
        x1 = x11

    y0 = 1*(-b2 * y1 - b3 * y2 + a1 * x0 + a2 * x1 + a3 * x22)

    # print("filtered")
    # print(y0)
    # print(y1)
    # print(y2)
    # print(x0)
    # print(x1)
    # print(x2)
    f = np.array([y0, y1, x00, x11])
    f[:, :2] = 0
    return f
############


class Server:

    def __init__(self):

        self.cutoff_freq = 10
        self.sample_time = 0.01
        self.frame = 0
        self.fl = 0
        self.data = ","
        # vicon is the client, subjectNames are the agent names, Segment names are subgroups of each agent
        self.vicon, self.segmentName, self.subjectNames, self.mover = vicon_init()
        self.xbee, self.remote_devicess, self.remote_names = xbee_init(self.subjectNames)  # This returns the xbee device,remote network, agents on the network
        self.plot = True

        self.ref = dict()
        self.vfilter = dict()
        self.rfilter = dict()
        self.pd_vals = dict()
        self.integral_vals = dict()
        self.pdata = dict()
        self.error_vals = dict()



        # perform a check for matching vicon and xbee agents
        self.t0 = time.time()
        self.active_agents = None
        self.nagents = len(self.subjectNames)
        self.t = 0
        self.data = dict()
        self.packet = None
        self.init_var()

        self.stop = False
        # self.live_plot(True)
        self.t = np.zeros((1,50), dtype = float)

        self.johnny_update()
        self.johnny_control()

        self.filtercycle()


        self.cycle()


    def johnny_update(self):
        # sleep(0.01)
        self.t[0,:-1] = self.t[0,1:]
        self.t[0,-1] = time.time() - self.t0
        self.vicon.GetFrame()

        for subName in self.subjectNames:

            pos = np.asarray(self.vicon.GetSegmentGlobalTranslation(subName, subName)[0])
            rot = np.asarray(self.vicon.GetSegmentGlobalRotationEulerXYZ(subName, subName)[0])

            ref_vrot = self.ref[subName][1]
            ref_vel = self.ref[subName][0]

            vf, pd = derivative_vel_filter(self.pdata[subName], pos)
            vflp, vd = lowpass_vel_filter(self.vfilter[subName], vf)

            self.pdata.update({subName: pd})
            self.vfilter.update({subName: vd})
            self.rfilter.update({subName: om_filter(self.rfilter[subName], rot)})
            self.mover[subName] = np.array([pos, rot, vflp, self.rfilter[subName][0]])



    def johnny_control(self):
        # sleep(0.01)
        self.t[0,:-1] = self.t[0,1:]
        self.t[0,-1] = time.time() - self.t0
        self.vicon.GetFrame()

        for subName in self.subjectNames:

            pos = np.asarray(self.vicon.GetSegmentGlobalTranslation(subName, subName)[0])
            rot = np.asarray(self.vicon.GetSegmentGlobalRotationEulerXYZ(subName, subName)[0])

            ref_vrot = self.ref[subName][1]
            ref_vel = self.ref[subName][0]

            vf, pd = derivative_vel_filter(self.pdata[subName], pos)
            vflp, vd = lowpass_vel_filter(self.vfilter[subName], vf)

            self.pdata.update({subName: pd})
            self.vfilter.update({subName: vd})
            self.rfilter.update({subName: om_filter(self.rfilter[subName], rot)})
            self.mover[subName] = np.array([pos, rot, vflp, self.rfilter[subName][0]])


            # velocity controller

            Rz = R.from_euler('z', rot[2], degrees=False).as_matrix()
            v = vflp / 1  # convert to m/s) and v is 3D vector (u v w)
            vr = self.rfilter[subName][0]

            Ev = self.error_vals[subName][0]
            Ew = self.error_vals[subName][1]

            Ev[:-1] = Ev[1:]
            Ew[:-1] = Ew[1:]
            Ev[-1] = ref_vel[0] - np.linalg.norm(v[:2])
            #Ew[-1] = ref_vrot[2] - vr[2]



            self.error_vals.update({subName: np.array([Ev,Ew])})
            # proportional
            Kpv = 10
            Kpw = 1

            # derivative
            Kdv = 0.1
            Kdw = 0.5

            # integral
            Kiv = 0.1 #0.01
            Kiw = 0.01 #0.005

            Kkv = 50
            Kkw = 1

            Heading_ref = 0
            #Heading = np.arctan2(v[1],v[0])*180/np.pi
            Heading = rot[2]*180/np.pi
            Heading_error = Heading_ref - Heading
            ref_vel[0]=0
            ref_vrot[2]=3*Heading_error
            Ew[-1] = ref_vrot[2] - vr[2]
            #ref_vrot[2]=0*np.pi/180

            vel = (Kkv*np.linalg.norm(ref_vel[0]))      +     (Kpv*Ev[-1] + Kdv * (Ev[-1] - Ev[-2]) + Kiv * sum(Ev))/500
            om = Kkw*ref_vrot[2]           +            Kpw*Ew[-1] + Kdw * (Ew[-1] - Ew[-2]) + np.minimum(Kiw*1,Kiw * sum(Ew))
            om = Kpw * Ew[-1] + Kdw * (Ew[-1] - Ew[-2]) + np.minimum(Kiw * 1, Kiw * sum(Ew))
            if om <= 30:
                data_rz = int((2 * om)) + 500  # 500 for going straight
            else:
                data_rz = int((1 * om)) + 500  # 500 for going straight

            data_rz = 500
            data_v = int(np.linalg.norm(vel) * 0.25) + 100
            #data_v = int(np.linalg.norm(vel))
            #data_rz = 500
            data_v = 100
            print('data rz   '+str(data_rz)+'data v   '+str(data_v))

            if (data_v > 1000):
                data_v = 1000

            if (data_rz > 650):
                data_rz = 650

            if (data_rz < 350):
                data_rz = 350

            dt = np.diff(self.t)
            #print( 'Ref Velocity : '+ str(ref_vel) +',   data_V : '+ str(data_v) + ',  Omega :'+str(om) + ',  data_w :'+ str(data_rz)+ ',  dt :' + str(np.max(dt)))
            #print('Ref Heading : ' + str(Heading_ref) + '    Heading : ' + str(rot[2]*180/np.pi) + '    Ref Velocity : '+ str(ref_vel[0]) +',   Ev : '+ str(Ev[-1])+',   Vel : '+ str(np.linalg.norm(v[:2]))+',   Vel_comm : '+ str(vel) +',   Rot_comm : '+ str(data_rz))
            print('Ref Heading : ' + str(Heading_ref) + '    Heading : ' + str(
                rot[2] * 180 / np.pi) + ',   Heading_error : ' + str(Heading_error) + '    Ref Velocity : ' + str(ref_vel[0]) + ',   Ev : ' + str(
                Ev[-1])  + ',   Om : ' + str(
                om) + ',   Rot_comm : ' + str(data_rz))

            self.data.update({subName: [data_v, data_rz]})


    @threaded



    def get_agents(self):
        # get agent names
        return self.subjectNames

    def get_frame(self):
        print('Vicon frame')

    def send_data(self):
        # broadcast
        i=0
        for name in self.remote_names:

            # print('iter' )
            # print(i)
            # print(self.mover[name])
            # print(name)
            d = str(self.mover[name][0])+ ',' + str(self.mover[name][1])
            d = str(self.data[name][0]) + "," + str(self.data[name][1])
            # print('d=',d)
            self.xbee.send_data_async(self.remote_devicess[i], d)
            # print('DATA')
            # print(name)
            # print(self.remote_devicess[i])
            # print(d)
            i=i+1




    @threaded
    def cycle(self):
        while (True):
            self.johnny_update()
            dt_max = np.max(np.diff(self.t))
            self.johnny_control()
            self.send_data()
            print('dt_max :' + str(dt_max))
            if self.stop == True:
                break


    def get_estimate(self):
        # print('')
        # return np.array([self.t, self.mover])
        return self.mover

    def end(self):

        print('Motor switched off')

    def start(self):
        print('Motor switched on')

    def battery_status(self):
        print('Battery Value')

    def init_var(self):
        for name in self.subjectNames:
            # Robot.ref[name] = np.array([[0,0,0],[0,0,0]])
            self.ref.update({name: np.array([[0, 0, 0], [0, 0, 0]])})
            self.vfilter.update({name: np.zeros((6, 3))})
            self.pdata.update({name: np.zeros((8, 3))})
            self.rfilter.update({name: np.zeros((4, 3))})

            # store proportional and derivative errors
            self.error_vals.update({name: np.zeros((2, 50))})

            # store integral errors
            self.integral_vals.update({name: np.zeros((2, 50))})

    def filtercycle(self):
        for i in range(100):
            self.johnny_update()
            self.johnny_control()

        for name in self.subjectNames:
            self.mover[name] = np.zeros((4, 3))


        veps = 1
        reps = 1
        while veps > 0.1 and reps > 0.1:
            #eps = 0
            self.johnny_update()
            self.johnny_control()

            for name in self.subjectNames:
                # eps = eps + np.linalg.norm(self.vfilter[name][0]) + np.linalg.norm(self.rfilter[name][0])
                veps = np.linalg.norm(self.vfilter[name][0])
                reps = np.linalg.norm(self.rfilter[name][0])
                # print(veps)
                # print(reps)






# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print('PyCharm')

    Robot = Server()

    pos = np.array([[0, 0, 0,0,0,0]])
    vel = np.array([[0, 0, 0,0,0,0]])

    rot = np.array([[0, 0, 0, 0, 0, 0]])
    rvel = np.array([[0, 0, 0, 0, 0, 0]])

    sp = []

    eps = 100
    t0 = time.time()
    print("start")
    print(t0 - time.time())
    D = 200

    while( time.time()-t0 < D):
        t = time.time()
        T = time.time()-t0


        for name in Robot.subjectNames:
            a = Robot.get_estimate()
            # print(a)
            p = a[name][0][:2]
            v = a[name][2][0]  # convert to m/s
            r = a[name][1][2]
            w = a[name][3][2]

            # print(v)

            # print(r)

            Kv = 1
            Kw = 1
            ep = [0,0] - p
            ref_v = Kv*np.linalg.norm(ep)
            ref_w = Kw*(np.arctan2(ep[1],ep[0])-r)


            # circle
            wd = 0
            # vx = 0.5*wd*math.sin(wd*T)
            # vy = 0.5*wd*math.cos(wd*T)
            v = 0
            # ref_v = 1000
            ref_v = 0
            ref_w = 0

            Robot.ref[name] = np.array([[ref_v, 0.0, 0.0], [0.0, 0.0, ref_w]])
    Robot.plot = False
    Robot.stop = True

    print("average", np.mean(np.diff(Robot.t[1:])))


    # stop the robot
    for name in Robot.subjectNames:
        Robot.ref[name] = np.array([[0, 0.0, 0.0], [0.0, 0.0, 0.0]])

    t = time.time()
    while (time.time() - t < 1):
        Robot.johnny_update()
        Robot.johnny_control()
        Robot.send_data()

        # live_update_demo(False) # 28 fps





