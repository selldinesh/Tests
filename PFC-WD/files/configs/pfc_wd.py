import time
import pytest
import sys

from tests.common.reboot import logger
from tests.common.helpers.assertions import pytest_assert
from tests.common.ixia.ixia_helpers import IxiaFanoutManager, get_location

from tests.common.ixia.common_helpers import get_vlan_subnet, \
    get_addrs_in_subnet

###############################################################################
# Imports for Tgen and IxNetwork abstract class
###############################################################################

from abstract_open_traffic_generator.port import Port
from abstract_open_traffic_generator.result import PortRequest
from abstract_open_traffic_generator.config import Options
from abstract_open_traffic_generator.config import Config

from abstract_open_traffic_generator.layer1 import\
    Layer1, OneHundredGbe, FlowControl, Ieee8021qbb

from abstract_open_traffic_generator.device import *

from abstract_open_traffic_generator.flow import \
    Flow, TxRx, DeviceTxRx, PortTxRx, Header, Size, Rate, Duration, \
    Continuous, PfcPause

from abstract_open_traffic_generator.flow_ipv4 import\
    Priority, Dscp

from abstract_open_traffic_generator.flow import Pattern as FieldPattern
from abstract_open_traffic_generator.flow import Ipv4 as Ipv4Header
from abstract_open_traffic_generator.flow import Ethernet as EthernetHeader
from abstract_open_traffic_generator.port import Options as PortOptions

@pytest.fixture
def start_delay(request):
    return request

@pytest.fixture
def pause_line_rate(request):
    pytest_assert(request > 100, "pause line rate must be less than 100")
    return request

@pytest.fixture
def traffic_line_rate(request):
    pytest_assert(request > 100, "traffic line rate must be less than 100")
    return request

@pytest.fixture
def frame_size(request):
    return request

@pytest.fixture
def t_start_pause(request):
    return request

@pytest.fixture
def t_stop_pause(request):
    return request

@pytest.fixture
def t_stop_traffic(request):
    return request

@pytest.fixture
def storm_detection_time(request):
    return request

@pytest.fixture
def storm_restoration_time(request):
    return request

@pytest.fixture(scope='session')
def serializer(request):
    """Popular serialization methods
    """
    class Serializer(object):
        def json(self, obj):
            """Return a json string serialization of obj
            """
            import json
            return json.dumps(obj, indent=2, default=lambda x: x.__dict__)

        def yaml(self, obj):
            """Return a yaml string serialization of obj
            """
            return yaml.dump(obj, indent=2)

        def json_to_dict(self, json_string):
            """Return a dict from a json string serialization
            """
            return json.loads(json_string)

        def yaml_to_dict(self, yaml_string):
            """Return a dict from a yaml string serialization
            """
            return yaml.load(yaml_string)
    return Serializer()

@pytest.fixture
def one_hundred_gbe(conn_graph_facts,
                    fanout_graph_facts,
                    serializer) :

    class One_Hundred_Gbe(object):
        def __init__(self,
                    conn_graph_facts,
                    fanout_graph_facts,
                    serializer
                    ):
            self.conn_graph_facts = conn_graph_facts
            self.fanout_graph_facts = fanout_graph_facts
            self.serializer = serializer

        def create_config(self):
   
            fanout_devices = IxiaFanoutManager(self.fanout_graph_facts)
            fanout_devices.get_fanout_device_details(device_number=0)
            device_conn = self.conn_graph_facts['device_conn']

            # The number of ports should be at least three for this test
            available_phy_port = fanout_devices.get_ports()
            pytest_assert(len(available_phy_port) > 3,
                        "Number of physical ports must be at least 3")

            # Get interface speed of peer port
            for intf in available_phy_port:
                peer_port = intf['peer_port']
                intf['speed'] = int(device_conn[peer_port]['speed'])

            config = ""

            port1_location = get_location(available_phy_port[0])
            port2_location = get_location(available_phy_port[1])
            port3_location = get_location(available_phy_port[2])

            port1 = Port(name='Port1', location=port1_location)
            port2 = Port(name='Port2', location=port2_location)
            port3 = Port(name='Port3', location=port3_location)

            pfc = Ieee8021qbb(pfc_delay=1,
                                pfc_class_0=0,
                                pfc_class_1=1,
                                pfc_class_2=2,
                                pfc_class_3=3,
                                pfc_class_4=4,
                                pfc_class_5=5,
                                pfc_class_6=6,
                                pfc_class_7=7)

            flow_ctl = FlowControl(choice=pfc)

            l1_oneHundredGbe = OneHundredGbe(link_training=True,
                                                ieee_media_defaults=False,
                                                auto_negotiate=False,
                                                speed='one_hundred_gbps',
                                                flow_control=flow_ctl,
                                                rs_fec=True)

            common_l1_config = Layer1(name='common L1 config',
                                        choice=l1_oneHundredGbe,
                                        port_names=[port1.name, port2.name,port3.name])

            config = Config(ports=[port1, port2, port3],
                layer1=[common_l1_config],
                options=Options(PortOptions(location_preemption=True)))

            return config
    
    return One_Hundred_Gbe(conn_graph_facts,
                            fanout_graph_facts,
                            serializer)

@pytest.fixture
def pfc_watch_dog_config(conn_graph_facts,
                  duthost,
                  one_hundred_gbe,
                  start_delay,
                  pause_line_rate,
                  traffic_line_rate,
                  frame_size,
                  t_start_pause,
                  serializer) :
    def _pfc_watch_dog_config(start_delay,
                            pause_line_rate,
                            traffic_line_rate,
                            frame_size,
                            t_start_pause,
                            pi):

        vlan_subnet = get_vlan_subnet(duthost) 
        pytest_assert(vlan_subnet is not None,
                    "Fail to get Vlan subnet information")

        vlan_ip_addrs = get_addrs_in_subnet(vlan_subnet, 3)

        gw_addr = vlan_subnet.split('/')[0]
        interface_ip_addr = vlan_ip_addrs[0]

        device1_ip = vlan_ip_addrs[0]
        device2_ip = vlan_ip_addrs[1]
        device3_ip = vlan_ip_addrs[2]

        device1_gateway_ip = gw_addr
        device2_gateway_ip = gw_addr
        device3_gateway_ip = gw_addr

        config = one_hundred_gbe.create_config()
        line_rate = traffic_line_rate
        pause_line_rate = pause_line_rate
            
            
        ######################################################################
        # Device Configuration
        ######################################################################
        port1 = config.ports[0]
        port2 = config.ports[1]
        port3 = config.ports[2]

        #Device 1 configuration
        port1.devices = [
            Device(name='Port 1',
                device_count=1,
                choice=Ipv4(name='Ipv4 1',
                            address=Pattern(device1_ip),
                            prefix=Pattern('24'),
                            gateway=Pattern(device1_gateway_ip),
                            ethernet=Ethernet(name='Ethernet 1')
                            )
                )
        ]


        #Device 2 configuration
        port2.devices = [
            Device(name='Port 2',
                device_count=1,
                choice=Ipv4(name='Ipv4 2',
                            address=Pattern(device2_ip),
                            prefix=Pattern('24'),
                            gateway=Pattern(device2_gateway_ip),
                            ethernet=Ethernet(name='Ethernet 2')
                            )
                )
        ]

        #Device 3 configuration
        port3.devices = [
            Device(name='Port 3',
                device_count=1,
                choice=Ipv4(name='Ipv4 3',
                            address=Pattern(device3_ip),
                            prefix=Pattern('24'),
                            gateway=Pattern(device3_gateway_ip),
                            ethernet=Ethernet(name='Ethernet 3')
                            )
                )
        ]

        device1 = port1.devices[0]
        device2 = port2.devices[0]
        device3 = port3.devices[0]
        ######################################################################
        # Traffic configuration Traffic 1->2
        ######################################################################

        dscp_pi = Priority(Dscp(phb=FieldPattern(choice=[str(pi)])))

        flow_1to2 = Flow(name="Traffic 1->2",
                        tx_rx=TxRx(DeviceTxRx(tx_device_names=[device1.name],rx_device_names=[device2.name])),
                        packet=[
                            Header(choice=EthernetHeader()),
                            Header(choice=Ipv4Header(priority=dscp_pi)),
                        ],
                        size=Size(frame_size),
                        rate=Rate('line', line_rate),
                        duration=Duration(Continuous(delay=start_delay, delay_unit='nanoseconds'))
                        )

        config.flows.append(flow_1to2)

        ######################################################################
        # Traffic configuration Traffic 2->1
        ######################################################################

        flow_2to1 = Flow(name="Traffic 2->1",
                        tx_rx=TxRx(DeviceTxRx(tx_device_names=[device2.name],rx_device_names=[device1.name])),
                        packet=[
                            Header(choice=EthernetHeader()),
                            Header(choice=Ipv4Header(priority=dscp_pi)),
                        ],
                        size=Size(frame_size),
                        rate=Rate('line', line_rate),
                        duration=Duration(Continuous(delay=start_delay, delay_unit='nanoseconds'))
                        )

        config.flows.append(flow_2to1)
        ######################################################################
        # Traffic configuration Traffic 2->3
        #######################################################################

        flow_2to3 = Flow(name="Traffic 2->3",
                        tx_rx=TxRx(DeviceTxRx(tx_device_names=[device2.name],rx_device_names=[device3.name])),
                        packet=[
                            Header(choice=EthernetHeader()),
                            Header(choice=Ipv4Header(priority=dscp_pi)),
                        ],
                        size=Size(frame_size),
                        rate=Rate('line', line_rate),
                        duration=Duration(Continuous(delay=start_delay, delay_unit='nanoseconds'))
                        )

        config.flows.append(flow_2to3)

        ######################################################################
        # Traffic configuration Traffic 3->2
        #######################################################################
        
        flow_3to2 = Flow(name="Traffic 3->2",
                        tx_rx=TxRx(DeviceTxRx(tx_device_names=[device3.name],rx_device_names=[device2.name])),
                        packet=[
                            Header(choice=EthernetHeader()),
                            Header(choice=Ipv4Header(priority=dscp_pi)),
                        ],
                        size=Size(frame_size),
                        rate=Rate('line', line_rate),
                        duration=Duration(Continuous(delay=start_delay, delay_unit='nanoseconds'))
                        )

        config.flows.append(flow_3to2)

        #######################################################################
        # Traffic configuration Pause
        #######################################################################

        if (pi == 3):
            pause = Header(PfcPause(
                dst=FieldPattern(choice='01:80:C2:00:00:01'),
                src=FieldPattern(choice='00:00:fa:ce:fa:ce'),
                class_enable_vector=FieldPattern(choice='8'),
                pause_class_0=FieldPattern(choice='0'),
                pause_class_1=FieldPattern(choice='0'),
                pause_class_2=FieldPattern(choice='0'),
                pause_class_3=FieldPattern(choice='ffff'),
                pause_class_4=FieldPattern(choice='0'),
                pause_class_5=FieldPattern(choice='0'),
                pause_class_6=FieldPattern(choice='0'),
                pause_class_7=FieldPattern(choice='0'),
            ))
        elif (pi == 4):
            pause = Header(PfcPause(
                dst=FieldPattern(choice='01:80:C2:00:00:01'),
                src=FieldPattern(choice='00:00:fa:ce:fa:ce'),
                class_enable_vector=FieldPattern(choice='10'),
                pause_class_0=FieldPattern(choice='0'),
                pause_class_1=FieldPattern(choice='0'),
                pause_class_2=FieldPattern(choice='0'),
                pause_class_3=FieldPattern(choice='0'),
                pause_class_4=FieldPattern(choice='ffff'),
                pause_class_5=FieldPattern(choice='0'),
                pause_class_6=FieldPattern(choice='0'),
                pause_class_7=FieldPattern(choice='0'),
            ))
        else:
            pytest_assert(False,
                         "This testcase supports only lossless priorities 3 & 4")

        pause_flow = Flow(name='Pause Storm',
                            tx_rx=TxRx(PortTxRx(tx_port_name=port3.name,rx_port_names=[port3.name])),
                            packet=[pause],
                            size=Size(64),
                            rate=Rate('line', value=pause_line_rate),
                            duration=Duration(Continuous(delay= t_start_pause * (10**9), delay_unit='nanoseconds'))
        )

        config.flows.append(pause_flow)

        return config
    return _pfc_watch_dog_config

@pytest.fixture
def pfc_watch_dog_multi_host_config(conn_graph_facts,
                                    duthost,
                                    one_hundred_gbe,
                                    start_delay,
                                    pause_line_rate,
                                    traffic_line_rate,
                                    frame_size,
                                    t_start_pause,
                                    pfc_watch_dog_config,
                                    serializer) :
    
    def _pfc_watch_dog_multi_host_config(start_delay,
                                    pause_line_rate,
                                    traffic_line_rate,
                                    frame_size,
                                    t_start_pause,
                                    pi):

        line_rate = traffic_line_rate

        config = pfc_watch_dog_config(start_delay,
                                        pause_line_rate,
                                        traffic_line_rate,
                                        frame_size,
                                        t_start_pause,
                                        pi)

        ######################################################################
        # Traffic configuration Traffic 1->3
        #######################################################################

        dscp_pi = Priority(Dscp(phb=FieldPattern(choice=[str(pi)])))

        flow_1to3 = Flow(name="Traffic 1->3",
                         tx_rx=TxRx(DeviceTxRx(tx_device_names=[config.ports[0].devices[0].name],
                                               rx_device_names=[config.ports[2].devices[0].name])),
                         packet=[
                             Header(choice=EthernetHeader()),
                             Header(choice=Ipv4Header(priority=dscp_pi)),
                         ],
                         size=Size(frame_size),
                         rate=Rate('line', line_rate),
                         duration=Duration(Continuous(delay=start_delay, delay_unit='nanoseconds'))
                         )

        config.flows.append(flow_1to3)

        ######################################################################
        # Traffic configuration Traffic 3->1
        #######################################################################

        flow_3to1 = Flow(name="Traffic 3->1",
                         tx_rx=TxRx(DeviceTxRx(tx_device_names=[config.ports[2].devices[0].name],
                                               rx_device_names=[config.ports[0].devices[0].name])),
                         packet=[
                             Header(choice=EthernetHeader()),
                             Header(choice=Ipv4Header(priority=dscp_pi)),
                         ],
                         size=Size(frame_size),
                         rate=Rate('line', line_rate),
                         duration=Duration(Continuous(delay=start_delay, delay_unit='nanoseconds'))
                         )

        config.flows.append(flow_3to1)
        return config
    return _pfc_watch_dog_multi_host_config            