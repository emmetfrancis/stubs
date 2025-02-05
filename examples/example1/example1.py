# # Simple example showcasing some of the features of STUBS
#
# Geometry is divided into 4 domains; two volumes, and two surfaces:
# - PM
# - Cytosol
# - Cytosol
#
# There are three function-spaces on the three domains:
# ```
# - u[Cyto] = [A, B]
# - u[ERm]  = [R, Ro]
# - u[ER]   = [AER]
# ```
#
# Roughly, this model is similar to an IP3 pulse at the PM, leading to Ca2+ release at the ER

# +
import os

import dolfin as d
import sympy as sym

from stubs import unit, config, common, mesh, model
from stubs.model_assembly import (
    Compartment,
    Parameter,
    Reaction,
    Species,
    sbmodel_from_locals,
)

# -

# First, we define the various units for the inputs

# Aliases - base units
uM = unit.uM
um = unit.um
molecule = unit.molecule
sec = unit.sec
# Aliases - units used in model
D_unit = um**2 / sec
flux_unit = molecule / (um**2 * sec)
vol_unit = uM
surf_unit = molecule / um**2


# Next we generate the model.


def make_model():
    # =============================================================================================
    # Species
    # =============================================================================================
    # name, initial concentration, concentration units, diffusion, diffusion units, compartment
    A = Species("A", 0.01, vol_unit, 1.0, D_unit, "Cyto")
    B = Species("B", 0.0, vol_unit, 1.0, D_unit, "Cyto")
    AER = Species("AER", 200.0, vol_unit, 5.0, D_unit, "ER")

    # Lets create an algebraic expression to define the initial condition of R
    Rinit = "(sin(40*y) + cos(40*z) + sin(40*x) + 3) * (y-x)**2"
    R1 = Species("R1", Rinit, surf_unit, 0.02, D_unit, "ERm")
    R1o = Species("R1o", 0.0, surf_unit, 0.02, D_unit, "ERm")
    # R2    = Species('R2'  , Rinit, surf_unit, 0   , D_unit, 'ERm')

    # =============================================================================================
    # Compartments
    # =============================================================================================
    # name, topological dimensionality, length scale units, marker value
    Cyto = Compartment("Cyto", 3, um, 1)
    PM = Compartment("PM", 2, um, 10)
    ER = Compartment("ER", 3, um, 2)
    ERm = Compartment("ERm", 2, um, 12)
    PM.specify_nonadjacency(["ERm", "ER"])
    ERm.specify_nonadjacency(["PM"])

    # =============================================================================================
    # Parameters and Reactions
    # =============================================================================================
    # Pulse function for B input at the PM
    # One way to prescribe a "pulse-like" flux is to define the flux as the derivative of a sigmoid
    # (here we choose atan as the sigmoid because of its simple derivative)
    Vmax, t0, m = 500, 0.1, 200
    t = sym.symbols("t")
    pulseI = Vmax * sym.atan(m * (t - t0))
    pulse = sym.diff(pulseI, t)
    j1pulse = Parameter.from_expression(
        "j1pulse", pulse, flux_unit, use_preintegration=True, preint_sym_expr=pulseI
    )
    r1 = Reaction(
        "r1",
        [],
        ["B"],
        param_map={"J": "j1pulse"},
        eqn_f_str="J",
        explicit_restriction_to_domain="PM",
    )

    # Degradation of B in the cytosol
    k2f = Parameter("k2f", 10, 1 / sec)
    r2 = Reaction(
        "r2", ["B"], [], param_map={"on": "k2f"}, reaction_type="mass_action_forward"
    )

    # Activating receptors on ERm with B
    k3f = Parameter("k3f", 100, 1 / (uM * sec))
    k3r = Parameter("k3r", 100, 1 / sec)
    r3 = Reaction("r3", ["B", "R1"], ["R1o"], {"on": "k3f", "off": "k3r"})

    # Release of A from ERm to cytosol
    k4Vmax = Parameter("k4Vmax", 2000, 1 / (uM * sec))
    r4 = Reaction(
        "r4",
        ["AER"],
        ["A"],
        param_map={"Vmax": "k4Vmax"},
        species_map={"R1o": "R1o", "uER": "AER", "u": "A"},
        eqn_f_str="Vmax*R1o*(uER-u)",
    )
    #   explicit_restriction_to_domain='ERm')

    # =============================================================================================
    # Gather all parameters, species, compartments and reactions
    # =============================================================================================
    return sbmodel_from_locals(locals().values())


# We load the model generated above, and load in the mesh we will use in this example.

# +
pc, sc, cc, rc = make_model()

# =============================================================================================
# Create/load in mesh
# =============================================================================================
# Base mesh
domain, facet_markers, cell_markers = common.DemoCuboidsMesh()
# Turn off "PM" on all sides of the cube except x=0
for face in d.faces(domain):
    if face.midpoint().x() > d.DOLFIN_EPS and facet_markers[face] == 10:
        facet_markers[face] = 0
# Write mesh and meshfunctions to file
os.makedirs("mesh", exist_ok=True)
common.write_mesh(domain, facet_markers, cell_markers, filename="mesh/DemoCuboidsMesh")

# # Define solvers
parent_mesh = mesh.ParentMesh(
    mesh_filename="mesh/DemoCuboidsMesh.h5",
    mesh_filetype="hdf5",
    name="parent_mesh",
)
config = config.Config()
model = model.Model(pc, sc, cc, rc, config, parent_mesh)
config.solver.update(
    {
        "final_t": 1,
        "initial_dt": 0.01,
        "time_precision": 6,
        "use_snes": True,
        "print_assembly": False,
    }
)

model.initialize(initialize_solver=False)
model.initialize_discrete_variational_problem_and_solver()

# Write initial condition(s) to file
results = dict()
os.makedirs("results", exist_ok=True)
for species_name, species in model.sc.items:
    results[species_name] = d.XDMFFile(
        model.mpi_comm_world, f"results/{species_name}.xdmf"
    )
    results[species_name].parameters["flush_output"] = True
    results[species_name].write(model.sc[species_name].u["u"], model.t)

# Solve
while True:
    # Solve the system
    model.monolithic_solve()
    # Save results for post processing
    for species_name, species in model.sc.items:
        results[species_name].write(model.sc[species_name].u["u"], model.t)
    # End if we've passed the final time
    if model.t >= model.final_t:
        break
