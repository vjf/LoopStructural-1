from FME.interpolators.piecewiselinear_interpolator import PiecewiseLinearInterpolator as PLI
from FME.supports.tet_mesh import TetMesh
from FME.modelling.geological_feature import GeologicalFeature, FaultedGeologicalFeature
from FME.visualisation.model_visualisation import LavaVuModelViewer
from FME.modelling.structural_frame import StructuralFrameBuilder
from FME.modelling.fault.fault_segment import FaultSegment
import numpy as np
import lavavu

"""
This is a basic example showing how to use the Piecewise Linear Interpolator for orientation and
value data points. 
"""
boundary_points = np.zeros((2,3))

boundary_points[0,0] = -20
boundary_points[0,1] = -20
boundary_points[0,2] = -20
boundary_points[1,0] = 20
boundary_points[1,1] = 20
boundary_points[1,2] = 20
mesh = TetMesh()
mesh.setup_mesh(boundary_points, nstep=1, n_tetra=10    000,)

interpolator = PLI(mesh,propertyname='Stratigraphy')
interpolator.add_point([0,0,0],0)
a = np.zeros((3,3,3))
interpolator.add_point([0,0,1],-0.5)
interpolator.add_strike_and_dip([0,0,0],90,0)
interpolator.setup_interpolator()
interpolator.solve_system(solver='lsmr')

support = interpolator.get_support()

feature = GeologicalFeature(0, 'Stratigraphy', support)


fault = StructuralFrameBuilder(interpolator=PLI,mesh=mesh,name='FaultSegment1')

fault.add_point([2.5,.5,1.5],0.,itype='gz')
fault.add_point([2.5,-.5,1.5],1.,itype='gz')


fault.add_point([10,0,-5],1.,itype='gy')

for y in range(-15,15):
    fault.add_point([18.,y,18],0,itype='gy')
    fault.add_point([10,y,-5],1.,itype='gy')

    fault.add_strike_dip_and_value([18.,y,18],strike=180,dip=35,val=0,itype='gx')

flag = mesh.nodes[:,2] < -5# dist>6000
flag = np.logical_and(flag,mesh.nodes[:,0]<10)
mesh.properties['flag'] = flag.astype(float)
flag = flag[mesh.elements]
flag = np.all(flag,axis=1)
ogw = 500
ogw = ogw / mesh.n_elements#np.sum(flag)#
# fault.interpolators['gx'].add_elements_gradient_orthogonal_constraint(np.arange(0,mesh.n_elements)[flag],np.array([0.,1.,0.])[None,:],w=ogw)
# fault.interpolators['gx'].add_elements_gradient_orthogonal_constraint(np.arange(0,mesh.n_elements)[flag],np.array([1.,0.,0.])[None,:],w=ogw)
ogw = 300
ogw /= mesh.n_elements
cgw = 500
cgw = cgw / mesh.n_elements
fault_frame = fault.build(
    solver='lsmr',
    guess=None,
   gxxgy=2*ogw,
   gxxgz=2*ogw,
   gyxgz=ogw,
   gxcg=cgw,
   gycg=cgw,
   gzcg=cgw,
   shape='rectangular',
    gx=True,
    gy=True,
    gz=True
)
#
fault = FaultSegment(fault_frame)

faulted_feature = FaultedGeologicalFeature(feature, fault)
viewer = LavaVuModelViewer()
viewer.plot_isosurface(faulted_feature.hw_feature,isovalue=0)
viewer.plot_isosurface(faulted_feature.fw_feature,isovalue=0)
mask = fault_frame.supports[0].get_node_values() > 0
print(mask[mesh.elements].shape)
print(mesh.n_nodes)
mask[mesh.elements] = np.any(mask[mesh.elements] == True, axis=1)[:, None]
print(mask)
viewer.plot_points(mesh.nodes[mask],"nodes",col="red")
#print(mask)
viewer.plot_structural_frame_isosurface(fault_frame, 0, isovalue=0, colour='blue')
# viewer.plot_structural_frame_isosurface(fault_frame,0,isovalue=2)
#
viewer.lv.interactive()