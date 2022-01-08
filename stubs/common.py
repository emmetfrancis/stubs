"""
General functions: array manipulation, data i/o, etc
"""
import pandas
import dolfin as d
import numpy as np
import scipy.interpolate as interp
import sys
import os
import re
import pint
from termcolor import colored
import stubs
from pandas import read_json
from contextlib import contextmanager

comm = d.MPI.comm_world
rank = comm.rank
size = comm.size
root = 0

def sub(func, idx):
    "This is just a hack patch to allow us to refer to a function/functionspace with no subspaces using .sub(0)"
    if isinstance(func, d.Function):
        if func.num_sub_spaces() <= 1 and idx == 0:
            return func
        else:
            return func.sub(idx)

    if isinstance(func, (d.MixedFunctionSpace, d.FunctionSpace)):
        if func.num_sub_spaces() <= 1 and idx == 0:
            return func
        else:
            return func.sub(idx).collapse()
    
    if isinstance(func, d.function.argument.Argument):
        if func.function_space().num_sub_spaces() <= 1 and idx == 0:
            return func
        else:
            return func[idx]
    
    raise AssertionError()


# pandas
class ref:
    """
    Pandas dataframe doesn't play nice with dolfin indexed functions since it will try
    to take the length but dolfin will not return anything. We use ref() to trick pandas
    into treating the dolfin indexed function as a normal object rather than something
    with an associated length
    """
    def __init__(self, obj): self.obj = obj
    def get(self):    return self.obj
    def set(self, obj):      self.obj = obj

def insert_dataframe_col(df, columnName, columnNumber=None, items=None):
    """
    pandas requires some weird manipulation to insert some things, e.g. dictionaries, as dataframe entries
    items is a list of things
    by default, will insert a column of empty dicts as the last column
    """
    if items == None:
        items = [{} for x in range(df.shape[0])]
    if columnNumber == None:
        columnNumber = df.columns.size
    df.insert(columnNumber, columnName, items)

def nan_to_none(df):
    return df.replace({np.nan: None})

def submesh_dof_to_mesh_dof(Vsubmesh, submesh, bmesh_emap_0, V, submesh_species_index=0, mesh_species_index=0, index=None):
    """
    Takes dof indices (single index or a list) on a submesh of a boundarymesh of a mesh and returns
    the dof indices of the original mesh.
    Based of the following forum posts:
    https://fenicsproject.org/qa/13595/interpret-vertex_to_dof_map-dof_to_vertex_map-function/
    https://fenicsproject.org/qa/6810/vertex-mapping-from-submesh-boundarymesh-back-actual-mesh/
    """
    idx = submesh_dof_to_vertex(Vsubmesh, submesh_species_index, index)
    idx = submesh_to_bmesh(submesh, idx)
    idx = bmesh_to_parent(bmesh_emap_0, idx)
    idx = mesh_vertex_to_dof(V, mesh_species_index, idx)
    return idx


# dolfin DOF indices are not guaranteed to be equivalent to the vertex indices of the corresponding mesh
def submesh_dof_to_vertex(Vsubmesh, species_index, index=None):
    num_species = Vsubmesh.num_sub_spaces()
    if num_species == 0: num_species = 1
    num_dofs = int(len(Vsubmesh.dofmap().dofs())/num_species)
    if index == None:
        index = range(num_dofs)

    mapping = d.dof_to_vertex_map(Vsubmesh)
    mapping = mapping[range(species_index,len(mapping),num_species)] / num_species
    mapping = [int(x) for x in mapping]

    return [mapping[x] for x in index]

def submesh_to_bmesh(submesh, index):
    submesh_to_bmesh_vertex = submesh.data().array("parent_vertex_indices", 0)
    return submesh_to_bmesh_vertex[index]

def bmesh_to_parent(bmesh_emap_0, index):
    if bmesh_emap_0.max() > 1e9: # unless the mesh has 1e9 vertices this is a sign of an error
        raise Exception("Error in bmesh_emap.")
    return bmesh_emap_0[index]

def mesh_vertex_to_dof(V, species_index, index):
    num_species = V.num_sub_spaces()
    if num_species == 0: num_species = 1

    mapping = d.vertex_to_dof_map(V)

    mapping = mapping[range(species_index, len(mapping), num_species)]

    return [mapping[x] for x in index]

def round_to_n(x,n):
    """
    Rounds to n sig figs
    """
    if x == 0:
        return 0
    else:
        sign = np.sign(x)
        x = np.abs(x)
        return sign*round(x, -int(np.floor(np.log10(x))) + (n - 1))


def interp_limit_dy(t,y,max_dy,interp_type='linear'):
    """
    Interpolates t and y such that dy between time points is never greater than max_dy
    Maintains all original t and y
    """
    interp_t = t.reshape(-1,1)
    dy_vec = y[1:] - y[:-1]

    for idx, dy in enumerate(dy_vec):
        npoints = np.int(np.ceil(np.abs(dy/max_dy))) - 1
        if npoints >= 1:
            new_t = np.linspace(t[idx], t[idx+1], npoints+2)[1:-1]
            interp_t = np.vstack([interp_t, new_t.reshape(-1,1)])

    interp_t = np.sort(interp_t.reshape(-1,))
    interp_y = interp.interp1d(t,y,kind=interp_type)(interp_t)

    return (interp_t, interp_y)

def sum_discrete_signals(ty1, ty2, max_dy=None):
    """
    ty1: Numpy array of size N1 x 2 where the first column is time and the
    second column is the first signal
    ty2: Numpy array of size N2 x 2 where the first column is time and the
    second column is the second signal

    ty1 and ty2 do not need to have the same dimensions (N1 does not have to
    equal N2). This function sums the linear interpolation of the two signals.

    tysum will have Nsum<=N1+N2 rows - signals will be summed at all time points
    from both ty1 and ty2 but not if there """
    assert type(ty1)==np.ndarray and type(ty2)==np.ndarray
    assert ty1.ndim==2 and ty2.ndim==2 # confirm there is a t and y vector
    t1 = ty1[:,0]; y1 = ty1[:,1]; t2 = ty2[:,0]; y2 = ty2[:,1]

    # get the sorted, unique values of t1 and t2
    tsum = np.sort(np.unique(np.append(t1,t2)))
    ysum = np.interp(tsum, t1, y1) + np.interp(tsum, t2, y2)

    if max_dy is not None:
        tsum, ysum = interp_limit_dy(tsum, ysum, max_dy)

    return np_smart_hstack(tsum, ysum)


def np_smart_hstack(x1, x2):
    """
    Quality of life function. Converts two (N,) numpy arrays or two lists into a
    (Nx2) array

    Example usage:
    a_list = [1,2,3,4]
    a_np_array = np.array([x**2 for x in a_list])
    np_smart_hstack(a_list, a_np_array)
    """
    onedim_types = [list, np.ndarray]
    assert type(x1) in onedim_types and type(x2) in onedim_types
    assert len(x1) == len(x2) # confirm same size
    if type(x1) == list: x1 = np.array(x1)
    if type(x2) == list: x2 = np.array(x2)

    return np.hstack([x1.reshape(-1,1), x2.reshape(-1,1)])

def append_meshfunction_to_meshdomains(mesh, mesh_function):
    md = mesh.domains()
    mf_dim = mesh_function.dim()

    for idx, val in enumerate(mesh_function.array()):
        md.set_marker((idx,val), mf_dim)

def color_print(full_text, color):
    if rank==root:
        split_text = [s for s in re.split('(\n)', full_text) if s] # colored doesn't like newline characters
        for text in split_text:
            if text == '\n':
                print()
            else:
                print(colored(text, color=color))

# ====================================================
# fancy printing
# ====================================================
def _fancy_print(title_text, buffer_color='cyan', text_color='green', filler_char='=',
                             num_banners=0, newlines=[0,0], left_justify=False, format_type=None):
    "Formatted text to stand out."
    # some default options
    if format_type == 'title':
        text_color = 'magenta'; num_banners = 1; newlines = [1,0]
    elif format_type == 'subtitle':
        text_color = 'green'; filler_char = '.'; left_justify=True
    elif format_type == 'log':
        buffer_color='white'; text_color = 'green'; filler_char = '.'; left_justify=True
    elif format_type == 'log_important':
        buffer_color='white'; text_color = 'magenta'; filler_char = '.'
    elif format_type == 'log_urgent':
        buffer_color='white'; text_color = 'red'; filler_char = '.'
    elif format_type == 'warning':
        buffer_color='orange'; text_color = 'red'; filler_char = '!'; num_banners=2; newlines=[1,1]
    elif format_type == 'timestep':
        text_color = 'magenta'; num_banners = 2; filler_char = '.'; newlines=[1,1]
    elif format_type == 'solverstep':
        text_color = 'magenta'; num_banners = 1; filler_char = '.'; newlines=[1,1]
    elif format_type is not None:
        raise ValueError("Unknown formatting_type.")

    # calculate optimal buffer size
    min_buffer_size = 5
    buffer_size = max([min_buffer_size, int((79 - len(title_text))/2 - 1)]) # terminal width == 80
    title_str_len = (buffer_size+1)*2 + len(title_text)
    parity=1 if title_str_len==78 else 0

    # color/stylize buffer, text, and banner
    buffer = lambda buffer_size: colored(filler_char*buffer_size, buffer_color)
    if left_justify:
        title_str=f"{colored(title_text, text_color)} {buffer(buffer_size*2+1+parity)}"
    else:
        title_str = f"{buffer(buffer_size)} {colored(title_text, text_color)} {buffer(buffer_size+parity)}"
    banner = colored(filler_char*(title_str_len+parity), buffer_color)

    # initial spacing
    if newlines[0] > 0: print('\n'*(newlines[0]-1))
    # print first banner
    for _ in range(num_banners):
        print(f"{banner}")
    # print main text
    print(title_str)
    # print second banner
    for _ in range(num_banners):
        print(f"{banner}")
    # end spacing
    if newlines[1] > 0: print('\n'*(newlines[1]-1))

# demonstrate built in options
def _fancy_print_options():
    for format_type in ['title', 'subtitle', 'log', 'log_important', 'log_urgent', 'timestep', 'solverstep']:
        _fancy_print(format_type, format_type=format_type)

# ====================================================
# I/O
# ====================================================

def json_to_ObjectContainer(json_str, data_type=None):
    """
    Converts a json_str (either a string of the json itself, or a filepath to
    the json)
    """
    if not data_type:
        raise Exception("Please include the type of data this is (parameters, species, compartments, reactions).")

    if json_str[-5:] == '.json':
        if not os.path.exists(json_str):
            raise Exception("Cannot find JSON file, %s"%json_str)   

    df = read_json(json_str).sort_index()
    df = nan_to_none(df)
    if data_type in ['parameters', 'parameter', 'param', 'p']:
        return stubs.model_assembly.ParameterContainer(df)
    elif data_type in ['species', 'sp', 'spec', 's']:
        return stubs.model_assembly.SpeciesContainer(df)
    elif data_type in ['compartments', 'compartment', 'comp', 'c']:
        return stubs.model_assembly.CompartmentContainer(df)
    elif data_type in ['reactions', 'reaction', 'r', 'rxn']:
        return stubs.model_assembly.ReactionContainer(df)
    else:
        raise Exception("I don't know what kind of ObjectContainer this .json file should be")



# def write_sbmodel(filepath, pdf, sdf, cdf, rdf):
#     """
#     Takes a ParameterDF, SpeciesDF, CompartmentDF, and ReactionDF, and generates
#     a .sbmodel file (a convenient concatenation of .json files with syntax
#     similar to .xml)
#     """
#     f = open(filepath, "w")

#     f.write("<sbmodel>\n")
#     # parameters
#     f.write("<parameters>\n")
#     pdf.df.to_json(f)
#     f.write("\n</parameters>\n")
#     # species
#     f.write("<species>\n")
#     sdf.df.to_json(f)
#     f.write("\n</species>\n")
#     # compartments
#     f.write("<compartments>\n")
#     cdf.df.to_json(f)
#     f.write("\n</compartments>\n")
#     # reactions
#     f.write("<reactions>\n")
#     rdf.df.to_json(f)
#     f.write("\n</reactions>\n")

#     f.write("</sbmodel>\n")
#     f.close()
#     print(f"sbmodel file saved successfully as {filepath}!")


def write_sbmodel(filepath, pc, sc, cc, rc):
    """
    Takes a ParameterDF, SpeciesDF, CompartmentDF, and ReactionDF, and generates
    a .sbmodel file (a convenient concatenation of .json files with syntax
    similar to .xml)
    """
    f = open(filepath, "w")

    f.write("<sbmodel>\n")
    # parameters
    f.write("<parameters>\n")
    pdf.df.to_json(f)
    f.write("\n</parameters>\n")
    # species
    f.write("<species>\n")
    sdf.df.to_json(f)
    f.write("\n</species>\n")
    # compartments
    f.write("<compartments>\n")
    cdf.df.to_json(f)
    f.write("\n</compartments>\n")
    # reactions
    f.write("<reactions>\n")
    rdf.df.to_json(f)
    f.write("\n</reactions>\n")

    f.write("</sbmodel>\n")
    f.close()
    print(f"sbmodel file saved successfully as {filepath}!")

def read_sbmodel(filepath, output_type=dict):
    f = open(filepath, "r")
    lines = f.read().splitlines()
    if lines[0] != "<sbmodel>":
        raise Exception(f"Is {filepath} a valid .sbmodel file?")

    p_string = []
    c_string = []
    s_string = []
    r_string = []
    line_idx = 0

    while True:
        if line_idx >= len(lines):
            break
        line = lines[line_idx]
        if line == '</sbmodel>':
            print("Finished reading in sbmodel file")
            break

        if line == '<parameters>':
            print("Reading in parameters")
            while True:
                line_idx += 1
                if lines[line_idx] == '</parameters>':
                    break
                p_string.append(lines[line_idx])

        if line == '<species>':
            print("Reading in species")
            while True:
                line_idx += 1
                if lines[line_idx] == '</species>':
                    break
                s_string.append(lines[line_idx])

        if line == '<compartments>':
            print("Reading in compartments")
            while True:
                line_idx += 1
                if lines[line_idx] == '</compartments>':
                    break
                c_string.append(lines[line_idx])

        if line == '<reactions>':
            print("Reading in reactions")
            while True:
                line_idx += 1
                if lines[line_idx] == '</reactions>':
                    break
                r_string.append(lines[line_idx])

        line_idx += 1

    pdf = pandas.read_json(''.join(p_string)).sort_index()
    sdf = pandas.read_json(''.join(s_string)).sort_index()
    cdf = pandas.read_json(''.join(c_string)).sort_index()
    rdf = pandas.read_json(''.join(r_string)).sort_index()
    pc = stubs.model_assembly.ParameterContainer(nan_to_none(pdf))
    sc = stubs.model_assembly.SpeciesContainer(nan_to_none(sdf))
    cc = stubs.model_assembly.CompartmentContainer(nan_to_none(cdf))
    rc = stubs.model_assembly.ReactionContainer(nan_to_none(rdf))

    if output_type==dict:
        return {'parameter_container': pc,   'species_container': sc, 
                'compartment_container': cc, 'reaction_container': rc}
    elif output_type==tuple:
        return (pc, sc, cc, rc)

# def create_sbmodel(p, s, c, r, output_type=dict):
#     pc = stubs.model_assembly.ParameterContainer(p)
#     sc = stubs.model_assembly.SpeciesContainer(s)
#     cc = stubs.model_assembly.CompartmentContainer(c)
#     rc = stubs.model_assembly.ReactionContainer(r)

#     if output_type==dict:
#         return {'parameter_container': pc,   'species_container': sc, 
#                 'compartment_container': cc, 'reaction_container': rc}
#     elif output_type==tuple:
#         return (pc, sc, cc, rc)

def empty_sbmodel():
    pc = stubs.model_assembly.ParameterContainer()
    sc = stubs.model_assembly.SpeciesContainer()
    cc = stubs.model_assembly.CompartmentContainer()
    rc = stubs.model_assembly.ReactionContainer()
    return pc, sc, cc, rc 

def pint_unit_to_quantity(pint_unit):
    if not isinstance(pint_unit, pint.Unit):
        raise TypeError("Input must be a pint unit")
    # returning pint.Quantity(1, pint_unit) changes the unit registry
    return 1.0*pint_unit 

def pint_quantity_to_unit(pint_quantity):
    if not isinstance(pint_quantity, pint.Quantity):
        raise TypeError("Input must be a pint quantity")
    if pint_quantity.magnitude != 1.0:
        raise ValueError("Trying to convert a pint quantity into a unit with magnitude != 1")
    return pint_quantity.units


# Some stack exchange code to redirect/suppress c++ stdout
# https://stackoverflow.com/questions/4675728/redirect-stdout-to-a-file-in-python/22434262#22434262
def _fileno(file_or_fd):
    fd = getattr(file_or_fd, 'fileno', lambda: file_or_fd)()
    if not isinstance(fd, int):
        raise ValueError("Expected a file (`.fileno()`) or a file descriptor")
    return fd

@contextmanager
def _stdout_redirected(to=os.devnull, stdout=None):
    if stdout is None:
       stdout = sys.stdout

    stdout_fd = _fileno(stdout)
    # copy stdout_fd before it is overwritten
    #NOTE: `copied` is inheritable on Windows when duplicating a standard stream
    with os.fdopen(os.dup(stdout_fd), 'wb') as copied: 
        stdout.flush()  # flush library buffers that dup2 knows nothing about
        try:
            os.dup2(_fileno(to), stdout_fd)  # $ exec >&to
        except ValueError:  # filename
            with open(to, 'wb') as to_file:
                os.dup2(to_file.fileno(), stdout_fd)  # $ exec > to
        try:
            yield stdout # allow code to be run with the redirected stdout
        finally:
            # restore stdout to its previous value
            #NOTE: dup2 makes stdout_fd inheritable unconditionally
            stdout.flush()
            os.dup2(copied.fileno(), stdout_fd)  # $ exec >&copied