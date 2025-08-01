# Oliver Gordon, 2019
# Compressed Sensing Implementation, Sanjit Masanam, 2025

import numpy as np
import random, math
import matplotlib.pyplot as plt
from scipy.spatial.distance import cdist

from nOmicron.mate import objects as mo
from nOmicron.microscope import IO
from tqdm import tqdm

def get_continuous_signal(channel_name, sample_time, sample_points):
    """Acquire a continuous signal.

    Parameters
    -----------
    channel_name : str
        The continuous channel to view, e.g. I_t, Z_t, Df_t, Aux1_t
    sample_time : float
        The time to acquire in seconds
    sample_points : int
        The number of points to acquire

    Returns
    -------
    x_data : Numpy array
    y_data : Numpy array

    Examples
    --------
    Acquire 60 points of I(t) data over 0.1 seconds
    >>> from nOmicron.microscope import IO
    >>> from nOmicron.utils.plotting import plot_linear_signal
    >>> IO.connect()
    >>> t, I = get_continuous_signal("I(t)", 1e-1, 60)
    >>> plot_linear_signal(v, I, "I(V)")
    >>> IO.disconnect()

    Acquire 100 points of Z(t) data over 5 seconds
    >>> from nOmicron.microscope import IO
    >>> from nOmicron.utils.plotting import plot_linear_signal
    >>> IO.connect()
    >>> t, I = get_continuous_signal("Z(t)", 5, 100)
    >>> plot_linear_signal(v, I, "I(V)")
    >>> IO.disconnect()
    """

    global view_count, x_data, y_data
    x_data = y_data = None
    view_count = 0

    def view_continuous_callback():
        global view_count, x_data, y_data
        view_count += 1
        pbar.update(1)

        data_size = mo.view.Data_Size()
        period = mo.clock.Period()
        x_data = np.linspace(0, (data_size - 1) * period, data_size)
        y_data = np.array(mo.sample_data(data_size))

    IO.enable_channel(channel_name)
    IO.set_clock(sample_time, sample_points)

    mo.view.Data(view_continuous_callback)
    mo.allocate_sample_memory(sample_points)

    pbar = tqdm(total=1)
    while view_count < 1 and mo.mate.rc == mo.mate.rcs['RMT_SUCCESS']:
        mo.wait_for_event()
    mo.clock.Enable(False)
    mo.view.Data()

    IO.disable_channel()

    return x_data, y_data


def get_point_spectra(channel_name, target_position, start_end, sample_time, sample_points,
                      repeats=1, forward_back=True, return_filename=False):
    """
    Go to a position and perform fixed point spectroscopy.

    Parameters
    ----------
    channel_name : str
        The channel to acquire from, e.g. I_V, Z_V, Aux2_V
    target_position : list
        [x, y] in the range -1,1. Can be converted from real nm units with utils.convert...
    start_end : tuple
        Start and end I/Z/Aux2
    sample_time : float
        The time to acquire in seconds
    sample_points : int
        The number of points to acquire
    repeats : int
        The number of repeat spectra to take for each point
    forward_back : bool
        Scan in both directions, or just one.
    return_filename : bool, optional
        If the full file name of the scan should be returned along with the data. Default is False

    Returns
    -------
    x_data : Numpy array
    y_data :
        If performing repeat spectra and:
            Scanning in both directions: list of list of Numpy arrays, where inner list is [0] forwards, [1] backwards
            Scanning in one direction: list of Numpy arrays
        If no repeat spectra and:
            Scanning in both directions: list of Numpy arrays, where list is [0] forwards, [1] backwards
            Scanning in one direction: single Numpy array

    Examples
    --------
    Acquire 60 points of I(V) data over 10 milliseconds, with tip placed in middle of scan window.
    >>> from nOmicron.microscope import IO
    >>> from nOmicron.utils.plotting import plot_linear_signal
    >>> IO.connect()
    >>> v, I = get_point_spectra("I(V)", start_end=[0, 1], target_position=[0, 0], ...
    >>>                   repeats=3, sample_points=50, sample_time=10e-3, forward_back=True)
    >>> plot_linear_signal(v, I, "I(V)")
    >>> IO.disconnect()
    """

    global view_count, view_name, x_data, y_data
    modes = {"V": 0, "Z": 1, "Varied Z": 2}  # Varied Z not fully supported yet!
    max_count = (repeats * (forward_back + 1))
    view_count = 0
    x_data = None
    y_data = []
    [y_data.append([None] * (bool(forward_back) + 1)) for i in range(repeats)]  # Can't use [] ** repeats

    def view_spectroscopy_callback():
        global view_count, view_name, x_data, y_data
        pbar.update(1)
        view_count += 1
        view_name = [mo.view.Run_Count(), mo.view.Cycle_Count()]
        cycle_count = mo.view.Cycle_Count() - 1
        packet_count = mo.view.Packet_Count() - 1
        data_size = mo.view.Data_Size()
        x_data = np.linspace(start_end[0], start_end[1], data_size)
        y_data[cycle_count][packet_count] = np.array(mo.sample_data(data_size))*1e-9
        if packet_count == 1:
            y_data[cycle_count][packet_count] = np.flip(y_data[cycle_count][packet_count])

    # Set all the parameters
    IO.enable_channel(channel_name)
    mo.spectroscopy.Spectroscopy_Mode(modes[channel_name[-2]])
    getattr(mo.spectroscopy, f"Device_{modes[channel_name[-2]] + 1}_Points")(sample_points)
    getattr(mo.spectroscopy, f"Raster_Time_{modes[channel_name[-2]] + 1}")(sample_time)
    getattr(mo.spectroscopy, f"Device_{modes[channel_name[-2]] + 1}_Start")(start_end[0])
    getattr(mo.spectroscopy, f"Device_{modes[channel_name[-2]] + 1}_End")(start_end[1])
    getattr(mo.spectroscopy, f"Device_{modes[channel_name[-2]] + 1}_Repetitions")(repeats)
    getattr(mo.spectroscopy, f"Enable_Device_{modes[channel_name[-2]] + 1}_Ramp_Reversal")(forward_back)

    # Set up spec
    mo.xy_scanner.Store_Current_Position(True)
    mo.xy_scanner.Target_Position(target_position)
    mo.xy_scanner.Trigger_Execute_At_Target_Position(True)

    # Do it
    mo.xy_scanner.move()
    mo.allocate_sample_memory(sample_points)
    mo.view.Data(view_spectroscopy_callback)

    pbar = tqdm(total=max_count)
    while view_count < max_count and mo.mate.rc == mo.mate.rcs['RMT_SUCCESS']:
        mo.wait_for_event()
    mo.view.Data()

    # Return to normal
    mo.xy_scanner.Trigger_Execute_At_Target_Position(False)
    mo.xy_scanner.Return_To_Stored_Position(True)
    mo.xy_scanner.Store_Current_Position(False)
    IO.disable_channel()

    if not forward_back:
        y_data = [item[0] for item in y_data]
    if repeats == 1:
        y_data = y_data[0]

    if return_filename:
        filename = f"{mo.experiment.Result_File_Path()}\\{mo.experiment.Result_File_Name()}--{view_count[0]}_{view_count[1]}.{channel_name}_mtrx"
        return x_data, y_data, filename
    else:
        return x_data, y_data

def get_compressed_sensing_scan_spectra(channel_name, inputProbDensArray, p, drift, start_end, sample_time, sample_points,
                      repeats=1, forward_back=True, return_filename=False, display_filepath=None):
    """
    Go to a position and perform fixed point spectroscopy.

    Parameters
    ----------
    channel_name : str
        The channel to acquire from, e.g. I_V, Z_V, Aux2_V
    inputProbDensArray : array, shape (n, n)
        Probability density array to guide random sampling to ignore/prioritize certain regions of window
    p : int
        Ratio of grid to randomly sample for CS
    drift : integer
        Drift speed value
    display_filepath : string (optional)
        Defaults to None; file path to save image of approx. optimal STM path
    start_end : tuple
        Start and end I/Z/Aux2
    sample_time : float
        The time to acquire in seconds
    sample_points : int
        The number of points to acquire
    repeats : int
        The number of repeat spectra to take for each point
    forward_back : bool
        Scan in both directions, or just one.
    return_filename : bool, optional
        If the full file name of the scan should be returned along with the data. Default is False

    Returns
    -------
    x_data : Numpy array
    y_data :
        If performing repeat spectra and:
            Scanning in both directions: list of list of Numpy arrays, where inner list is [0] forwards, [1] backwards
            Scanning in one direction: list of Numpy arrays
        If no repeat spectra and:
            Scanning in both directions: list of Numpy arrays, where list is [0] forwards, [1] backwards
            Scanning in one direction: single Numpy array

    Examples
    --------
    Acquire 60 points of I(V) data over 10 milliseconds, with tip placed in middle of scan window.
    >>> from nOmicron.microscope import IO
    >>> from nOmicron.utils.plotting import plot_linear_signal
    >>> IO.connect()
    >>> v, I = get_point_spectra("I(V)", start_end=[0, 1], target_position=[0, 0], ...
    >>>                   repeats=3, sample_points=50, sample_time=10e-3, forward_back=True)
    >>> plot_linear_signal(v, I, "I(V)")
    >>> IO.disconnect()
    """

    approx_optimal_path_arr, approx_optimal_path_length = compressedSensing(inputProbDensArray, p, drift, display_filepath)

    x_data_total_lst = []
    y_data_total_lst = []
    filename_total_lst = []

    global view_count, view_name, x_data, y_data
    modes = {"V": 0, "Z": 1, "Varied Z": 2}  # Varied Z not fully supported yet!
    max_count = (repeats * (forward_back + 1))
    view_count = 0
    x_data = None
    y_data = []
    [y_data.append([None] * (bool(forward_back) + 1)) for i in range(repeats)]  # Can't use [] ** repeats

    def view_spectroscopy_callback():
        pbar.update(1)
        view_count += 1
        view_name = [mo.view.Run_Count(), mo.view.Cycle_Count()]
        cycle_count = mo.view.Cycle_Count() - 1
        packet_count = mo.view.Packet_Count() - 1
        data_size = mo.view.Data_Size()
        x_data = np.linspace(start_end[0], start_end[1], data_size)
        y_data[cycle_count][packet_count] = np.array(mo.sample_data(data_size))*1e-9
        if packet_count == 1:
            y_data[cycle_count][packet_count] = np.flip(y_data[cycle_count][packet_count])

    # Set all the parameters
    IO.enable_channel(channel_name)
    mo.spectroscopy.Spectroscopy_Mode(modes[channel_name[-2]])
    getattr(mo.spectroscopy, f"Device_{modes[channel_name[-2]] + 1}_Points")(sample_points)
    getattr(mo.spectroscopy, f"Raster_Time_{modes[channel_name[-2]] + 1}")(sample_time)
    getattr(mo.spectroscopy, f"Device_{modes[channel_name[-2]] + 1}_Start")(start_end[0])
    getattr(mo.spectroscopy, f"Device_{modes[channel_name[-2]] + 1}_End")(start_end[1])
    getattr(mo.spectroscopy, f"Device_{modes[channel_name[-2]] + 1}_Repetitions")(repeats)
    getattr(mo.spectroscopy, f"Enable_Device_{modes[channel_name[-2]] + 1}_Ramp_Reversal")(forward_back)

    for x, y in approx_optimal_path_arr:
        # Set up spec
        mo.xy_scanner.Store_Current_Position(True)
        mo.xy_scanner.Target_Position([x, y])
        mo.xy_scanner.Trigger_Execute_At_Target_Position(True)

        # Do it
        mo.xy_scanner.move()
        mo.allocate_sample_memory(sample_points)
        mo.view.Data(view_spectroscopy_callback)

        pbar = tqdm(total=max_count)
        while view_count < max_count and mo.mate.rc == mo.mate.rcs['RMT_SUCCESS']:
            mo.wait_for_event()
        mo.view.Data()

        # Parse and append data to total data lists
        if not forward_back:
            y_data = [item[0] for item in y_data]
        if repeats == 1:
            y_data = y_data[0]

        if return_filename:
            filename = f"{mo.experiment.Result_File_Path()}\\{mo.experiment.Result_File_Name()}--{view_count[0]}_{view_count[1]}.{channel_name}_mtrx"
            x_data_total_lst.append(x_data)
            y_data_total_lst.append(y_data)
            filename_total_lst.append(filename)
        else:
            x_data_total_lst.append(x_data)
            y_data_total_lst.append(y_data)

        # Reset data-taking variables
        modes = {"V": 0, "Z": 1, "Varied Z": 2}  # Varied Z not fully supported yet!
        max_count = (repeats * (forward_back + 1))
        view_count = 0
        x_data = None
        y_data = []
        [y_data.append([None] * (bool(forward_back) + 1)) for i in range(repeats)]  # Can't use [] ** repeats

    # Return to normal
    mo.xy_scanner.Trigger_Execute_At_Target_Position(False)
    mo.xy_scanner.Return_To_Stored_Position(True)
    mo.xy_scanner.Store_Current_Position(False)
    IO.disable_channel()

    return x_data_total_lst, y_data_total_lst, filename_total_lst

def compressedSensing(inputProbDensArray, p, drift, display_filepath=None):
    '''
    Compressed Sensing implemention with a NN-TSP algorithm

    Parameters
    ----------
    inputProbDensArray : array, shape (n, n)
        Probability density array to guide random sampling to ignore/prioritize certain regions of window
    p : int
        Ratio of grid to randomly sample for CS
    drift : integer
        Drift speed value
    display_filepath : string (pptional)
        File path to save image of proposed STM path

    Returns
    -------
    approx_optimal_path_arr : array, shape (path_length, 2)
        Array ordered with each point in approx. optimal path 
    approx_optimal_path_length: int
        Length of approx. optimal path
    '''

    # Ensure inputProbDensArray fits criteria
    if len(inputProbDensArray.shape) != 2:
        raise Exception("inputProbDensArray must be of dimension 2")
    elif inputProbDensArray.shape[0] != inputProbDensArray.shape[1]:
        raise Exception("inputProbDensArray must be square array")
    
    # Ensure p is in range [0,1]
    if (p > 1) or (p < 0):
        raise Exception("p must be between 0 and 1")

    # Find TSP_points
    flat_input = inputProbDensArray.flatten()/np.sum(inputProbDensArray.flatten())
    choice_1D_arr = np.linspace(0, len(flat_input)-1, num=len(flat_input))
    TSP_points = np.random.choice(a=choice_1D_arr, size=math.ceil(p*len(flat_input)), replace=False, p=flat_input)
    print("# of measurement points", len(TSP_points))


    scale_const = 2/(inputProbDensArray.shape[0]-1)

    # Define useful variables/arrays
    n = 0
    max_sum = 0
    start_n = 0
    coord_arr = np.zeros([math.ceil(p*len(flat_input)), 2])

    # Loop to calculate coordinates for TSP algorithm
    for point in TSP_points:
        x = 1 - math.floor(point/inputProbDensArray.shape[0]) * scale_const
        y = (-1) + (point % inputProbDensArray.shape[0]) * scale_const
        coord_arr[n] = [x, y]

        if np.abs(x)+np.abs(y) > max_sum:
            max_sum, start_n = np.abs(x)+np.abs(y), n
        n += 1

    start_coord = coord_arr[start_n]

    def nn_tsp_matrix(coords, start_idx=0):
        """
        Greedy NN‐TSP using a precomputed distance matrix.

        Parameters
        ----------
        coords : array‐like, shape (n_points, dim)
        start_idx : int
            Index in coords to start the path.
        
        Returns
        -------
        tour : ndarray, shape (n_points, dim)
            Coords in path order
        """
        coords = np.asarray(coords)
        n = coords.shape[0]
        
        # Precompute all pairwise distances once:
        D = cdist(coords, coords)               # shape (n, n)
        
        visited = np.zeros(n, dtype=bool)
        tour = np.empty(n, dtype=int)
        
        current = start_idx
        visited[current] = True
        tour[0] = current
        
        for i in range(1, n):
            # mask out already‐visited cities with +inf
            D[current, visited] = np.inf
            # pick the nearest unvisited
            nxt = D[current].argmin()
            tour[i] = nxt
            visited[nxt] = True
            current = nxt
        
        return coords[tour]

    def distance(coord_1, coord_2):
        return np.sqrt(np.sum((coord_1 - coord_2)**2))

    def tour_length(tour):
        "The total of distances between each pair of consecutive cities in the tour."
        return sum(distance(tour[i], tour[i-1]) 
                for i in range(len(tour)))

    approx_optimal_path = nn_tsp_matrix(coord_arr, start_n)
    approx_optimal_path_length = tour_length(approx_optimal_path)
    approx_optimal_path_arr = np.array(approx_optimal_path)

    if display_filepath != None:
        fig, ax = plt.subplots()
        ax.grid(False)
        ax.scatter(coord_arr[:,0],coord_arr[:,1],s=20)
        ax.plot(approx_optimal_path_arr[:,0],approx_optimal_path_arr[:,1], '--go', label='Best Route', linewidth=2.5)
        plt.title("TSP Best Path using NN")
        plt.legend()
        fig.set_size_inches(8, 6)   
        plt.savefig(display_filepath)
    
    return approx_optimal_path_arr, approx_optimal_path_length

if __name__ == '__main__':
    from nOmicron.utils.plotting import plot_linear_signal
    IO.connect()
    t, I1 = get_continuous_signal("I(t)", sample_time=5, sample_points=50)

    # Do a fixed point spec
    v, I2 = get_point_spectra("I(V)", start_end=(0.5, -0.5), target_position=[0, 0.5],
                              repeats=4, sample_points=100, sample_time=20e-3, forward_back=True)
    plot_linear_signal(v, I2, "I(V)")
    IO.disconnect()