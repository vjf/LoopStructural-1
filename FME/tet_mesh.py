import meshpy.tet
from meshpy import *
#from sympy import Symbol, Matrix
#from sympy.utilities.autowrap import autowrap
import numpy as np
from numpy import linalg as la
from .dsi_helper import get_element, compute_cg_regularisation_constraint, pointintetra, cg, cg_cstr_to_coo_sq
from .marching_tetra import marching_tetra
from scipy.spatial import cKDTree
from sklearn.decomposition import PCA
import os
class TetMesh:
    """
    A class containing the geometry of a tetrahedral mesh.
    Nodes are the vertices
    Elements are the tetrahedrons
    Neighbours are the neighbours
    Vertex properties are stored as a dict of np arrrays self.properties
    Element properties are self.property_gradients 
    """ 
    
    def __init__(self,name='TetMesh',path='./'):
        """
        Creates a mesh object. This just assigns the mesh a name and a location to save
        """
        self.path=path
        self.name=name
        self.mesh = None
        self.shared_idxs = np.zeros(3,dtype=np.int)
        self.dinfo = {}
        self.cg_calculated = {}
        self.properties = {}
        self.property_gradients = {}
        self.property_gradients_nodes = {}
        self.element_gradients = {}
        self.element_nodes_to_id = {}
        self.regions = {}
        
    def setup_mesh(self,boundary_points,**kwargs):#maxvol=0.001,nstep=100):
        """
        Build a mesh given the boundary points
        Can define the resolution of the mesh using the kwargs
         
        n_tetra: number of tetrahedron
        maxvol: maximum volume for a single tetra - if both are specified this one is used.
        """
        self.pca = PCA(n_components=3)
        minx = boundary_points[0,0]
        miny = boundary_points[0,1]
        minz = boundary_points[0,2]
        maxx = boundary_points[1,0]
        maxy = boundary_points[1,1]
        maxz = boundary_points[1,2]
        points = np.array([
        (minx, miny, minz),
        ( maxx, miny, minz),
        ( maxx,  maxy, minz),
        (minx,  maxy, minz),
        (minx, miny,  maxz),
        ( maxx, miny,  maxz),
        ( maxx,  maxy,  maxz),
        (minx,  maxy,  maxz)
        ])
        #calculate the 3 principal components to find the local coordinate system
        self.pca.fit(points)
        #project the points into this coordinate system
        newp = self.pca.transform(points)
        n_tetra = 4000#maxvol=0.001
        if 'n_tetra' in kwargs:
            n_tetra = kwargs['n_tetra']
        #calculate the volume of the bounding box
        maxvol = 0.001
        if 'maxvol' not in kwargs:
            lengthU = maxx-minx
            lengthV = maxy-miny
            lengthW = maxz-minz
            boxVol = lengthU*lengthW*lengthV
            correction_factor = 1.91
            maxvol = correction_factor*boxVol / n_tetra 
        if 'maxvol' in kwargs:
            maxvol = kwargs['maxvol']
        
        facets = [
                [0, 1, 2, 3],
                [4, 5, 6, 7],
                [0, 4, 5, 1],
                [1, 5, 6, 2],
                [2, 6, 7, 3],
                [3, 7, 4, 0]
                ]

        # create the mesh
        info = meshpy.tet.MeshInfo()
        #use the projected points to build the mesh
        info.set_points(newp)
        info.set_facets(facets)
        meshpy_mesh = meshpy.tet.build(info, max_volume=maxvol,options=meshpy.tet.Options('pqn'))
        self.nodes = self.pca.inverse_transform(np.array(meshpy_mesh.points))
        self.elements = np.array(meshpy_mesh.elements)
        self.neighbours = np.array(meshpy_mesh.neighbors)
        self.n_nodes = len(self.nodes)
        self.n_elements = len(self.elements)
        self.barycentre = np.sum(self.nodes[self.elements][:,:,:],axis=1) / 4.
        self.tree = cKDTree(self.barycentre)
        self.minx =minx #np.min(newp[:,0])#minx
        self.miny =miny #np.min(newp[:,1])#miny
        self.minz =minz #np.min(newp[:,2])#minz
        self.maxx =maxx #np.max(newp[:,0])#maxx
        self.maxy =maxy #np.max(newp[:,1])#maxy
        self.maxz =maxz #np.max(newp[:,2])#maxz
            
        self.minpc0= np.min(newp[:,0])
        self.maxpc0= np.max(newp[:,0])
        self.minpc1= np.min(newp[:,1])
        self.maxpc1= np.max(newp[:,1])
        self.minpc2= np.min(newp[:,2])
        self.maxpc2= np.max(newp[:,2])

        self.regions['everywhere'] = np.ones(self.n_nodes).astype(bool)
    def add_region(self,region,name):
        self.regions[name] = region
        self.properties['REGION_'+name] = region.astype(float)
    def update_property(self,name,value,save=True):
        self.properties[name] = value
        #grad = np.zeros((self.elements.shape[0],3))
        grads = self.get_elements_gradients(np.arange(self.n_elements))
        props = self.properties[name][self.elements[np.arange(self.n_elements)]]
        grad = np.einsum('ikj,ij->ik',grads,props)
        self.property_gradients[name] = grad
        if save:
            self.save()
        #//self.property_v = p
    def transfer_gradient_to_nodes(self,propertyname):
        grad = np.zeros((self.nodes.shape[0],3))
        for i, e in enumerate(self.elements):
            for n in e:
                grad[n,:]+=self.property_gradients[propertyname][i,:]
        grad/=4
        self.property_gradients_nodes[propertyname] = grad
            
    def get_neighbours(self,t):
        return self.neighbours[t]
    def get_neighbors(self,t):
        return self.get_neighbours(t) #spelling >.<
    def get_shared_face(self,t1,t2):
        self.shared_idxs[:] = 0
        i = 0
        for p in t1: #for nodes in tetra1
            if p in t2: #if node in tetra2
                self.shared_idxs[i] = p
                i+=1
        shared_points = self.nodes[self.shared_idxs[:i]] #find the locations of shared points
        v1 = shared_points[0,:]-shared_points[1,:]
        v2 = shared_points[2,:]-shared_points[1,:]
        n = np.cross(v1,v2)#v1 * v2
        return n,shared_points,self.shared_idxs
    def calculate_constant_gradient(self,region,shape='rectangular'):
        self.dinfo = np.zeros(self.n_elements).astype(bool)
        A = []
        B = []
        row = []
        col = []
        c_ = 0
        
        #add cg constraint for all of the 
        EG = self.get_elements_gradients(np.arange(self.n_elements))
        idc, c,ncons = cg(EG,self.neighbours,self.elements,self.nodes)
        idc=np.array(idc)
        c = np.array(c)
        if shape == 'rectangular':
            for i in range(ncons):
                for j in range(5):
                    A.append(c[i,j])
                    row.append(i)
                    col.append(idc[i,j])
                B.append(0.)
        c_=ncons            
        if shape == 'square':
            A, row, col = cg_cstr_to_coo_sq(c,idc,ncons)
            A = np.array(A).tolist()
            row = np.array(row).tolist()
            col = np.array(col).tolist()
        self.cg_calculated[shape] = True
        self.cg = [A,B,row,col,c_]
        return True
    def get_constant_gradient(self,w=0.1,region='everywhere',**kwargs):
        shape = 'rectangular'
        if 'shape' in kwargs:
            shape = 'square'
        self.calculate_constant_gradient(region,**kwargs)
        return self.cg[0],self.cg[1],self.cg[2],self.cg[3],self.cg[4]
    def get_elements_gradients(self,e):
        """
        Returns the gradient of the elements using their global index.
        Speed up using numpy
        """
        ps = self.nodes[self.elements[e]]
        ps -= ps[:,0,:][:,None]
        J = np.ones((len(e),3,1))
        O = np.ones((len(e),1,3))
        m = ps[:,1:,:]
        Minv = np.zeros((len(e),4,4))
        Minv[:,0,0] = 1
        Minv[:,0,1:] = 0
        minv = np.linalg.inv(m)
        Minv[:,1:,0] = (-minv@J)[:,:,0]
        Minv[:,1:,1:] = minv
        I = np.zeros((3,4))
        I[np.arange(3),np.arange(3)+1] = 1
        return I@Minv

    def calc_bary_c(self,e,p):
        """
        Calculate the barycentre coordinates for an array of n elements 
        and n points
        """ 
        points = self.nodes[self.elements[e]]
        npts = len(e)
        vap = np.zeros((3,npts))
        vbp = np.zeros((3,npts))
    
        vcp = np.zeros((3,npts))
        vdp = np.zeros((3,npts))
        vab = np.zeros((3,npts))
        vac = np.zeros((3,npts))
        vad = np.zeros((3,npts))
        vbc = np.zeros((3,npts))
        vbd = np.zeros((3,npts))
        ##bp = 
        vap= p - points[:,0,:]
        vbp= p - points[:,1,:]
        vcp= p - points[:,2,:]
        vdp= p - points[:,3,:]
        vab= points[:,1,:] - points[:,0,:]
        vac= points[:,2,:] - points[:,0,:] 
        vad= points[:,3,:] - points[:,0,:] 
        vbc= points[:,2,:] - points[:,1,:] 
        vbd= points[:,3,:] - points[:,1,:] 
        
        va = np.sum(vbp * np.cross(vbd,vbc,axisa=1,axisb=1), axis=1) /6.
        vb = np.sum(vap * np.cross(vac,vad,axisa=1,axisb=1), axis=1) /6.
        vc = np.sum(vap * np.cross(vad,vab,axisa=1,axisb=1), axis=1) /6.
        vd = np.sum(vap * np.cross(vab,vac,axisa=1,axisb=1), axis=1) /6.
        v = np.sum(vab * np.cross(vac,vad,axisa=1,axisb=1), axis=1) /6.
        c = np.zeros((4,npts))
        c[0,:] = va / v
        c[1,:] = vb / v
        c[2,:] = vc / v
        c[3,:] = vd / v
        return c
    def elements_for_array(self,array,k=10):
        #find the nearest k elements for the arrays
        #reducing k could speed up calculation but migh add errors
        
        d,ee = self.tree.query(array) 
        
        iarray = self.pca.transform(array)
        inside = np.zeros(array.shape[0]).astype(bool)
        inside[:] = True
        inside = iarray[:,0] > self.minpc0[None] 
        inside*= iarray[:,0] < self.maxpc0[None]
        inside*= iarray[:,1] > self.minpc1[None]
        inside*= iarray[:,1] < self.maxpc1[None]
        inside*= iarray[:,2] > self.minpc2[None]
        inside*= iarray[:,2] < self.maxpc2[None]

        return ee, inside
    def eval_interpolant(self,array,prop,k=5,e=None,region='everywhere'):
        """Evaluate an interpolant from property on an array of points.
        Uses numpy to speed up calculations but could be expensive for large mesh/points
        """
        if e == None:
            e, inside = self.elements_for_array(array,k)
        else:
            inside = np.array(e.shape).astype(bool)
            inside[:] = True

        bc = self.calc_bary_c(e[inside],array[inside])
        prop_int = np.zeros(e.shape)

        props = self.properties[prop][self.elements[e[inside]]]
        prop_int[inside]=np.sum((bc.T*props),axis=1)
        prop_int[~inside]=np.nan
        return prop_int
    def element_property_value(self,prop):
        bc = np.zeros(4)
        bc[:] = 0.25
        e = np.arange(self.n_elements)
        prop_int = np.zeros(e.shape)
        
        props = self.properties[prop][self.elements[e]]
        prop_int=np.sum((bc.T*props),axis=1)
        return prop_int
    def element_property_gradient(self,prop):
        e = np.arange(self.n_elements)
        
        ps = self.nodes[self.elements[e]]
        m= np.array(
        [[(ps[:,1,0]-ps[:,0,0]),(ps[:,1,1]-ps[:,0,1]),(ps[:,1,2]-ps[:,0,2])],
            [(ps[:,2,0]-ps[:,0,0]),(ps[:,2,1]-ps[:,0,1]),(ps[:,2,2]-ps[:,0,2])],
            [(ps[:,3,0]-ps[:,0,0]),(ps[:,3,1]-ps[:,0,1]),(ps[:,3,2]-ps[:,0,2])]])
        I = np.array(
                  [[-1.,1.,0.,0.],
                   [-1.,0.,1.,0.],
                   [-1.,0.,0.,1.]])
        m = np.swapaxes(m,0,2)
        grads = la.inv(m)

        grads = grads.swapaxes(1,2)
        grads = grads @ I
        vals = self.properties[prop][self.elements[e]]
        #grads = np.swapaxes(grads,1,2)
        a = np.zeros((self.n_elements,3))#array.shape)
        a = (grads*vals[:,None,:]).sum(2)/4.# @ vals.T/
        a /= np.sum(a,axis=1)[:,None]
        return a
        

    def eval_gradient(self,array,prop,k=5,region='everywhere'):
        """Evaluate an interpolant from property on an array of points.
        Uses numpy to speed up calculations but could be expensive for large mesh/points
        """    
        e, inside = self.elements_for_array(array,k)
        ps = self.nodes[self.elements[e[inside]]]
        m= np.array(
        [[(ps[:,1,0]-ps[:,0,0]),(ps[:,1,1]-ps[:,0,1]),(ps[:,1,2]-ps[:,0,2])],
            [(ps[:,2,0]-ps[:,0,0]),(ps[:,2,1]-ps[:,0,1]),(ps[:,2,2]-ps[:,0,2])],
            [(ps[:,3,0]-ps[:,0,0]),(ps[:,3,1]-ps[:,0,1]),(ps[:,3,2]-ps[:,0,2])]])
        I = np.array(
                  [[-1.,1.,0.,0.],
                   [-1.,0.,1.,0.],
                   [-1.,0.,0.,1.]])
        m = np.swapaxes(m,0,2)
        grads = la.inv(m)

        grads = grads.swapaxes(1,2)
        grads = grads @ I
        vals = self.properties[prop][self.elements[e[inside]]]
        a = np.zeros(array.shape)
        a[inside] = (grads*vals[:,None,:]).sum(2)/4.# @ vals.T/
        a[~inside,:]=np.nan
        a /= np.sum(a,axis=1)[:,None]
        return a
        
    def export_to_vtk(self,name='mesh.vtk'):
        import meshio
        meshio.write_points_cells(name,
                          self.nodes,{"tetra": self.elements},
                          point_data=self.properties,
                         cell_data={'tetra':self.property_gradients} 
                         )
        
        meshio.write_points_cells('test.vtk',
                          self.nodes,{"tetra": self.elements},
                          point_data=self.property_gradients_nodes
                         )
    def save(self):
        self.export_to_vtk(self.path+self.name+'.vtk')
    def plot_mesh(self,propertyname,cmap=None):
        try:
            import vista
        except ImportError:
            print("Cannot import PyVista/vista")
            return

        vmesh = vista.read(self.path+self.name+'.vtk')
        p = vista.Plotter(notebook=True)
        p.set_background('white')
        p.add_mesh(
            vmesh,
            cmap=cmap,
            show_scalar_bar=False,
            scalars=self.properties[propertyname],
            interpolate_before_map=True
        )
        p.show()
    def lv_plot_isosurface(self,propertyname,lv,**kwargs):
        #import lavavu in case its not imported
        try:
            import lavavu  #visualisation library   
        except ImportError:
            print("Cannot import Lavavu")
            return 
        #if no isovalue is specified just use the average
        property = self.properties[propertyname]
        slices = [np.mean(property)]
        colour='red'
        if 'isovalue' in kwargs:
            slices = [kwargs['isovalue']]
        if 'slices' in kwargs:
            slices = kwargs['slices']
        if 'nslices' in kwargs:
            slices = np.linspace(np.min(property),np.max(property),kwargs['nslices'])
        if 'colour' in kwargs:
            colour=kwargs['colour']
        for isovalue in slices:
            if isovalue < np.min(property) or isovalue > np.max(property):
                print("No surface to create for isovalue")
                isovalue=kwargs['isovalue']
            reg = np.zeros(self.properties[propertyname].shape).astype(bool)
            reg[:] = True
            if 'region' in kwargs:
                reg = self.regions[kwargs['region']]
            name = propertyname+'_%f'%isovalue
            if 'name' in kwargs:
                name = kwargs['name']
            
            tri, ntri = marching_tetra(isovalue,self.elements,self.nodes,reg,self.properties[propertyname])
    
            ##convert from memoryview to np array
            tri = np.array(tri)
            ntri = np.array(ntri)[0]
            ##create a triangle indices array and initialise to -1
            tris = np.zeros((ntri,3)).astype(int)
            tris[:,:] = -1
            ##create a dict for storing nodes index where the key is the node as as a tuple. 
            #A dict is preferable because it is very quick to check if a key exists
            #assemble arrays for unique vertex and triangles defined by vertex indices
            nodes = {}
            n = 0 #counter
            for i in range(ntri):
                for j in range(3):
                    if tuple(tri[i,j,:]) in nodes:
                        tris[i,j] = nodes[tuple(tri[i,j,:])]
                    else:
                        nodes[tuple(tri[i,j,:])] = n
                        tris[i,j] = n
                        n+=1
            #find the normal vector to the faces using the vertex order
            a = tri[:ntri, 0, :] - tri[:ntri, 1, :]
            b = tri[:ntri, 0, :] - tri[:ntri, 2, :]

            crosses = np.cross(a, b)
            crosses = crosses / (np.sum(crosses ** 2, axis=1) ** (0.5))[:, np.newaxis]

            #get barycentre of faces and findproperty gradient from scalar field
            tribc = np.mean(tri[:ntri,:,:],axis=1)
            tribc = tribc[np.any(np.isnan(tribc),axis=1)]
            propertygrad=self.eval_gradient(tribc,prop='strati')
            propertygrad/=np.linalg.norm(propertygrad,axis=1)[:,None]

             #dot product between gradient and normal indicates if faces are incorrectly ordered
            dotproducts = (propertygrad * crosses[np.any(np.isnan(tribc),axis=1)]).sum(axis=1)
            #
            if dot product >0 then adjust triangle indexing
                indices = (dotproducts>0).nonzero()[0]
                tris[indices] = tris[indices,::-1]
            nodes_np = np.zeros((n,3))
            for v in nodes.keys():
                nodes_np[nodes[v],:] = np.array(v)
            surf = lv.triangles(name)
            surf.vertices(nodes_np)
            surf.indices(tris)
            surf.colours(colour)
        return lv
    def lv_plot_vector_field(self,propertyname,lv,**kwargs):
        try:
            import lavavu
        except ImportError:
            print("Cannot import Lavavu")
        if 'colour' not in kwargs:
            kwargs['colour'] = 'black'
        vectorslicing = 100
        if 'vectorslicing' in kwargs:
            vectorslicing = kwargs['vectorslicing']
        vector = self.property_gradients[propertyname]
        #normalise
        vector/=np.linalg.norm(vector,axis=1)[:,None]
        vectorfield = lv.vectors(propertyname+"_grad",**kwargs)
        vectorfield.vertices(self.barycentre[::vector_slicing,:])
        vectorfield.vectors(vectors)
        return
