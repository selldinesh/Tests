import pytest

@pytest.fixture(scope='module')
def test_bgp_convergence_config(api):
    """
    1.Configure IPv4 EBGP sessions between the test ports
    2.Advertise IPv4 routes
    3.Configure and advertise same IPv4 routes
    4.Configure another IPv4 session to send the traffic.
    """
    config = api.config()
    port1, port2, port3 = config.ports \
    .port(name='Test Port 1', location='10.36.78.53;09;06') \
    .port(name='Test Port 2', location='10.36.78.53;09;07') \
    .port(name='Test Port 3', location='10.36.78.53;09;08') 
    
    #Topology Creation
    
    Topology1, Topology2, Topology3 = config.devices \
    .device(name='Topology 1',container_name=port1.name,device_count=1) \
    .device(name='Topology 2',container_name=port2.name,device_count=1) \
    .device(name='Topology 3',container_name=port3.name,device_count=1) 

    #L1 settings
    config.options.port_options.location_preemption = True
    for test_port in [port1,port2,port3]:
        layer1 = config.layer1.layer1()[-1]
        layer1.name = '%s port settings'%test_port.name
        layer1.port_names = [test_port.name]
        layer1.auto_negotiate = False
        layer1.ieee_media_defaults = False
        layer1.auto_negotiation.link_training = False
        layer1.auto_negotiation.rs_fec = False
        layer1.speed= "speed_100_gbps"

    #
    #Topology 1
    tx_eth=Topology1.ethernet
    tx_eth.name='Ethernet 1'
    tx_ipv4=tx_eth.ipv4
    tx_ipv4.name='IPv4 1'
    tx_ipv4.address.value = '30.1.1.2'
    tx_ipv4.gateway.value = '30.1.1.1'
    tx_ipv4.prefix.value = 31
    
    #Topology 2
    rx1_eth=Topology2.ethernet
    rx1_eth.name='Ethernet 2'
    rx1_ipv4=rx1_eth.ipv4
    rx1_ipv4.name='IPv4 2'
    rx1_ipv4.address.value = '31.1.1.2'
    rx1_ipv4.gateway.value = '31.1.1.1'
    rx1_ipv4.prefix.value = 31
    rx1_bgpv4 = rx1_ipv4.bgpv4
    rx1_bgpv4.name = "BGP 2"
    rx1_bgpv4.as_type = "ebgp"
    rx1_bgpv4.dut_ipv4_address.value = "31.1.1.1"
    rx1_bgpv4.as_number.value = "65200"
    rx1_rr = rx1_bgpv4.bgpv4_route_ranges.bgpv4routerange()[-1]
    rx1_rr.name = "Network Group 2"
    rx1_rr.address_count = "1000"
    rx1_rr.address.value = "200.1.0.1"
    rx1_rr.prefix.value = "32"

    
    #Topology 3
    rx2_eth=Topology3.ethernet
    rx2_eth.name='Ethernet 3'
    rx2_ipv4=rx2_eth.ipv4
    rx2_ipv4.name='IPv4 3'
    rx2_ipv4.address.value = '32.1.1.2'
    rx2_ipv4.gateway.value = '32.1.1.1'
    rx2_ipv4.prefix.value = 31
    rx2_bgpv4 = rx2_ipv4.bgpv4
    rx2_bgpv4.name = "BGP 3"
    rx2_bgpv4.as_type = "ebgp"
    rx2_bgpv4.dut_ipv4_address.value = "32.1.1.1"
    rx2_bgpv4.as_number.value = "65200"
    rx2_rr = rx2_bgpv4.bgpv4_route_ranges.bgpv4routerange()[-1]
    rx2_rr.name = "Network Group 3"
    rx2_rr.address_count = "1000"
    rx2_rr.address.value = "200.1.0.1"
    rx2_rr.prefix.value = "32"
    #
    
    flow = config.flows.flow(name='convergence_test')[-1]
    flow.tx_rx.device.tx_names = [Topology1.name]
    flow.tx_rx.device.rx_names = [rx1_rr.name, rx2_rr.name]
    flow.size.fixed = "1024"
    flow.rate.percentage = "100"
    #api.set_config(config)
    return config

