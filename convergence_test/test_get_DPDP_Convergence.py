import pytest
import sys
import time
from tabulate import tabulate
from statistics import mean
sys.path.append('/regression/test-cases/ixnetwork/one-time-use/nanite/sonic_project/convergence_test/')
from test_BGP_Config_Creation import test_bgp_convergence_config
#def test_bgp_dp_dp_convergence(api, utils, bgp_convergence_config):
@pytest.mark.dut
def test_bgp_dp_dp_convergence(api, test_bgp_convergence_config):
    """
    1. Get the frames tx rate
    2. Trigger withdraw routes by link down on port1
    3. Wait for sometime and stop the traffic
    4. Obtain tx frames and rx frames from stats and calculate average
       dp/dp convergence for multiple iterations
    """
    response= api.set_config(test_bgp_convergence_config)
    assert(len(response.errors)) == 0
    # name of the port that should be shutdown to trigger withdraw route
    rx_port1 = test_bgp_convergence_config.ports[1].name
    rx_port2 = test_bgp_convergence_config.ports[2].name
    # Trigger withdraw routes by doing a link down on port1
    def get_flow_stats(api):
            request = api.metrics_request()
            request.flow.flow_names = []
            return api.get_metrics(request).flow_metrics
    
    def is_port_rx_stopped(api, port_name):
        """
        Returns true if port is down
        """
        req = api.metrics_request()
        req.port.port_names = [port_name]
        port_stats = api.get_metrics(req).port_metrics
        if int(port_stats[0].frames_rx_rate) == 0:
            return True
        return False
    
    def getAvgDPDPConvergenceTime(portName,iter):
        table,avg=[],[]
        for i in range(0,iter):
            print('|-------------------Iteration : {} --------------|'.format(i+1))
            print('Starting Traffic')
            ts = api.transmit_state()
            ts.state = ts.START
            response=api.set_transmit_state(ts)
            assert(len(response.errors)) == 0
            time.sleep(10)
            flow_stats=get_flow_stats(api)
            tx_frame_rate = flow_stats[0].frames_tx_rate
            assert tx_frame_rate != 0
            print('Simulating Link Failure on {} Port'.format(portName))
            ls = api.link_state()
            ls.port_names = [portName]
            ls.state = ls.DOWN
            api.set_link_state(ls)
            #assert(len(response.errors)) == 0
            time.sleep(5)
            assert is_port_rx_stopped(api,portName) == True
            flow_stats=get_flow_stats(api)
            tx_frame_rate = flow_stats[0].frames_tx_rate
            assert tx_frame_rate != 0
            # Stop traffic
            print('Stopping Traffic')
            ts = api.transmit_state()
            ts.state = ts.STOP
            api.set_transmit_state(ts)
            #assert(len(response.errors)) == 0
            time.sleep(5)
            flow_stats=get_flow_stats(api)
            tx_frames = flow_stats[0].frames_tx
            rx_frames = sum([fs.frames_rx for fs in flow_stats])
            # Calculate Convergence
            dp_convergence = (tx_frames - rx_frames) * 1000 / tx_frame_rate
            print("DP/DP Convergence Time: {} ms".format(int(dp_convergence)))  
            avg.append(int(dp_convergence))
            print('Simulating Link Up on {} at the end of iteration {}'.format(portName,i+1))
            ls.state = ls.UP
            api.set_link_state(ls)
            #assert(len(response.errors)) == 0
            assert is_port_rx_stopped(api,portName) == False
        table.append('%s Link Failure'%portName)
        table.append(iter)
        table.append(mean(avg))
        return table
    
    table=[]
    test_iterations=1
    table.append(getAvgDPDPConvergenceTime(rx_port1,test_iterations))
    table.append(getAvgDPDPConvergenceTime(rx_port2,test_iterations))
    columns=['Event Name','Iterations','Avg Calculated DP/DP Convergence Time(ms)']
    print("\n%s" % tabulate(table,headers=columns,tablefmt="psql"))
    print('Done')