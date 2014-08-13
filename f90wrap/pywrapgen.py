# HF XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
# HF X
# HF X   f90wrap: F90 to Python interface generator with derived type support
# HF X
# HF X   Copyright James Kermode 2011
# HF X
# HF X   These portions of the source code are released under the GNU General
# HF X   Public License, version 2, http://www.gnu.org/copyleft/gpl.html
# HF X
# HF X   If you would like to license the source code under different terms,
# HF X   please contact James Kermode, james.kermode@gmail.com
# HF X
# HF X   When using this software, please cite the following reference:
# HF X
# HF X   http://www.jrkermode.co.uk/f90wrap
# HF X
# HF XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

import os
import logging

from f90wrap import fortran as ft
from f90wrap import codegen as cg


def format_call_signature(node):
    if isinstance(node, ft.Procedure):
        sig = ''
        if isinstance(node, ft.Function):
            sig += ', '.join(ret_val.py_name for ret_val in node.ret_val)
            sig += ' = '
        if 'constructor' in node.attributes:
            sig += node.type_name.title()
        elif 'destructor' in node.attributes:
            return 'Destructor for class %s' % node.type_name.title()
        else:
            if hasattr(node, 'method_name'):
                sig += node.method_name
            else:
                sig += node.name
        sig += '('
        had_optional = False
        for i, arg in enumerate(node.arguments):
            if not had_optional and 'optional' in arg.attributes:
                sig += '['
                had_optional = True
            if i != 0:
                sig += ', '
            sig += arg.py_name
        if had_optional:
            sig += ']'
        sig += ')'
        return sig
    elif isinstance(node, ft.Module):
        return 'Module %s' % node.name
    elif isinstance(node, ft.Element):
        return ('Element %s ftype=%s pytype=%s' %
                  (node.name, node.type,
                   ft.f2py_type(node.type)))
    else:
        return str(node)

def format_doc_string(node):
    """
    Generate Python docstring from Fortran docstring and call signature
    """

    def _format_line_no(lineno):
        """
        Format Fortran source code line numbers

        FIXME could link to source repository (e.g. github)
        """
        if isinstance(lineno, slice):
            return 'lines %d-%d' % (lineno.start, lineno.stop - 1)
        else:
            return 'line %d' % lineno

    doc = [format_call_signature(node), '']
    doc.append('')
    doc.append('Defined at %s %s' % (node.filename, _format_line_no(node.lineno)))

    # For procedures, write required parameters and return values in numpydoc format
    if isinstance(node, ft.Procedure):
        doc.append('')
        # Input parameters
        i = 0
        for arg in node.arguments:
            pytype = ft.f2py_type(arg.type, arg.attributes)
            if "intent(out)" not in arg.attributes:
                if i == 0:
                    doc.append("Parameters")
                    doc.append("----------")
                i += 1
                doc.append("%s : %s" % (arg.name, pytype))
                if arg.doc:
                    for d in arg.doc:
                        doc.append("\t%s" % d)
                    doc.append("")

        i = 0
        for arg in node.arguments:
            pytype = ft.f2py_type(arg.type, arg.attributes)
            if "intent(out)" in arg.attributes:
                if i == 0:
                    doc.append("Returns")
                    doc.append("-------")
                i += 1
                doc.append("%s : %s" % (arg.name, pytype))
                doc.append("\t%s" % arg.doc)
                doc.append("")

    doc += [''] + node.doc[:]  # incoming docstring from Fortran source

    return '\n'.join(['"""'] + doc + ['"""'])


class PythonWrapperGenerator(ft.FortranVisitor, cg.CodeGenerator):
    def __init__(self, prefix, mod_name, types, imports=None,
                 f90_mod_name=None, make_package=False, kind_map=None):
        cg.CodeGenerator.__init__(self, indent=' ' * 4,
                               max_length=80,
                               continuation='\\',
                               comment='#')
        ft.FortranVisitor.__init__(self)
        self.prefix = prefix
        self.py_mod_name = mod_name
        if f90_mod_name is None:
            f90_mod_name = '_' + mod_name
        self.f90_mod_name = f90_mod_name
        self.types = types
        if imports is None:
            imports = [(self.f90_mod_name, None),
                       ('f90wrap.sizeof_fortran_t', None),
                       ('f90wrap.arraydata', 'get_array'),
                       ('f90wrap.fortrantype', ('FortranDerivedType', 'FortranDerivedTypeArray'))]
        self.imports = set(imports)
        self.make_package = make_package
        if kind_map is None:
            kind_map = {}
        self.kind_map = kind_map

    def write_imports(self):
        for (mod, symbol) in self.imports:
            if symbol is None:
                self.write('import %s' % mod)
            elif isinstance(symbol, tuple):
                self.write('from %s import %s' % (mod, ', '.join(symbol)))
            else:
                self.write('from %s import %s' % (mod, symbol))
        self.write()
        self.write('_sizeof_fortran_t = f90wrap.sizeof_fortran_t.sizeof_fortran_t()')
        self.write('_empty_fortran_t = [0]*_sizeof_fortran_t')
        self.write('_empty_type = FortranDerivedType.from_handle(_empty_fortran_t)')
        self.write()

    def visit_Root(self, node):
        """
        Wrap subroutines and functions that are outside of any Fortran modules
        """
        if self.make_package:
            if not os.path.exists(self.py_mod_name):
                os.mkdir(self.py_mod_name)
                        
        self.code = []
        self.py_mods = []
        self.write_imports()            

        self.generic_visit(node)

        if self.make_package:
            for py_mod in self.py_mods:
                self.write('import %s.%s' % (self.py_mod_name, py_mod))
            py_wrapper_file = open(os.path.join(self.py_mod_name, '__init__.py'), 'w')
        else:
            py_wrapper_file = open('%s.py' % self.py_mod_name, 'w')
        py_wrapper_file.write(str(self))
        py_wrapper_file.close()

    def visit_Module(self, node):
        logging.info('PythonWrapperGenerator visiting module %s' % node.name)
        cls_name = node.name.title()
        node.dt_array_initialisers = []

        if self.make_package:
            self.code = []
            self.write(format_doc_string(node))
            self.write_imports()
            self.write('_arrays = {}')
            self.write('_objs = {}')
            self.write()                      
        else:
            self.write('class %s(FortranModule):' % cls_name)
            self.indent()
            self.write(format_doc_string(node))

            if len(node.elements) == 0 and len(node.types) == 0 and len(node.procedures) == 0:
                self.write('pass')

        self.generic_visit(node)

        for el in node.elements:
            dims = filter(lambda x: x.startswith('dimension'), el.attributes)
            if len(dims) == 0:  # proper scalar type (normal or derived)
                if el.type.startswith('type'):
                    self.write_dt_wrappers(node, el)
                else:
                    self.write_scalar_wrappers(node, el)
            elif el.type.startswith('type'):  # array of derived types
                self.write_dt_array_wrapper(node, el, dims)
            else:
                self.write_sc_array_wrapper(node, el, dims)

        self.write('_dt_array_initialisers = [%s]' % (', '.join(node.dt_array_initialisers)))
        self.write()

        if self.make_package:
            self.write('''for init_array in _dt_array_initialisers:
    init_array()
            ''')
            if len(self.code) > 0:
                py_wrapper_file = open(os.path.join(self.py_mod_name, node.name+'.py'), 'w')
                py_wrapper_file.write(str(self))
                py_wrapper_file.close()
                self.py_mods.append(node.name)
            self.code = []
        else:
            self.dedent()  # finish the FortranModule class
            self.write()
            # instantise the module class
            self.write('%s = %s()' % (node.name, node.name.title()))
            self.write()


    def write_constructor(self, node):
        handle_arg = ft.Argument(name='handle',
                              filename=node.filename,
                              doc=['Opaque reference to existing derived type instance'],
                              lineno=node.lineno,
                              attributes=['intent(in)', 'optional'],
                              type='integer')
        handle_arg.py_name = 'handle'

        # special case for constructors: return value is 'self' argument,
        # plus we add an extra optional argument
        args = node.ret_val + node.arguments + [handle_arg]

        dct = dict(func_name=node.name,
                   prefix=self.prefix,
                   mod_name=self.f90_mod_name,
                   py_arg_names=', '.join(['%s%s' % (arg.py_name,
                                                     'optional' in arg.attributes and '=None' or '')
                                                     for arg in args ]),
                   f90_arg_names=', '.join(['%s=%s' % (arg.name, arg.py_value) for arg in node.arguments]))

        self.write("def __init__(%(py_arg_names)s):" % dct)
        self.indent()
        self.write(format_doc_string(node))
        self.write('FortranDerivedType.__init__(self)')
        self.write('self._handle = %(mod_name)s.%(prefix)s%(func_name)s(%(f90_arg_names)s)' % dct)
        self.dedent()
        self.write()

        
    def write_destructor(self, node):
        dct = dict(func_name=node.name,
                   prefix=self.prefix,
                   mod_name=self.f90_mod_name,
                   py_arg_names=', '.join(['%s%s' % (arg.py_name,
                                                     'optional' in arg.attributes and '=None' or '')
                                                     for arg in node.arguments]),
                   f90_arg_names=', '.join(['%s=%s' % (arg.name, arg.py_value) for arg in node.arguments]))
        self.write("def __del__(%(py_arg_names)s):" % dct)
        self.indent()
        self.write(format_doc_string(node))
        self.write('if self._alloc:')
        self.indent()
        self.write('%(mod_name)s.%(prefix)s%(func_name)s(%(f90_arg_names)s)' % dct)
        self.dedent()
        self.dedent()
        self.write()


    def visit_Procedure(self, node):
        logging.info('PythonWrapperGenerator visiting routine %s' % node.name)
        if 'constructor' in node.attributes:
            self.write_constructor(node)
        elif 'destructor' in node.attributes:
            self.write_destructor(node)
        else:
            dct = dict(func_name=node.name,
                       method_name=hasattr(node, 'method_name') and node.method_name or node.name,
                       prefix=self.prefix,
                       mod_name=self.f90_mod_name,
                       py_arg_names=', '.join(['%s%s' % (arg.py_name,
                                                     ('optional' in arg.attributes or arg.value is None)
                                                     and '=None' or '')
                                                     for arg in node.arguments ]),
                       f90_arg_names=', '.join(['%s=%s' % (arg.name, arg.py_value) for arg in node.arguments]),
                       call='')

            if isinstance(node, ft.Function):
                dct['result'] = ', '.join([ret_val.name for ret_val in node.ret_val])
                dct['call'] = '%(result)s = ' % dct

            if not self.make_package and (node.type_name is None and node.mod_name is not None):
                # module procedures become static methods
                self.write('@staticmethod')
            self.write("def %(method_name)s(%(py_arg_names)s):" % dct)
            self.indent()
            self.write(format_doc_string(node))
            call_line = '%(call)s%(mod_name)s.%(prefix)s%(func_name)s(%(f90_arg_names)s)' % dct
            self.write(call_line)

            if isinstance(node, ft.Function):
                # convert any derived type return values to Python objects
                for ret_val in node.ret_val:
                    if ret_val.type.startswith('type'):
                        cls_name = ft.strip_type(ret_val.type).title()
                        cls_mod_name = self.types[ft.strip_type(ret_val.type)].mod_name + '.'
                        self.write('%s = %s%s.from_handle(%s)' %
                                   (ret_val.name, cls_mod_name, cls_name, ret_val.name))
                self.write('return %(result)s' % dct)

            self.dedent()
            self.write()


    def visit_Type(self, node):
        logging.info('PythonWrapperGenerator visiting type %s' % node.name)
        node.dt_array_initialisers = []
        cls_name = node.name.title()
        self.write('class %s(FortranDerivedType):' % cls_name)
        self.indent()
        self.write(format_doc_string(node))
        self.generic_visit(node)

        for el in node.elements:
            dims = filter(lambda x: x.startswith('dimension'), el.attributes)
            if len(dims) == 0:  # proper scalar type (normal or derived)
                if el.type.startswith('type'):
                    self.write_dt_wrappers(node, el)
                else:
                    self.write_scalar_wrappers(node, el)
            elif el.type.startswith('type'):  # array of derived types
                self.write_dt_array_wrapper(node, el, dims)
            else:
                self.write_sc_array_wrapper(node, el, dims)

        self.write('_dt_array_initialisers = [%s]' % (', '.join(node.dt_array_initialisers)))
        self.write()
        self.dedent()


    def write_scalar_wrappers(self, node, el):
        dct = dict(el_name=el.name,
                   el_name_get=el.name, el_name_set=el.name,
                   mod_name=self.f90_mod_name,
                   prefix=self.prefix, type_name=node.name,
                   self='self',
                   selfdot='self.',
                   selfcomma='self, ',
                   handle=isinstance(node, ft.Type) and 'self._handle' or '')
        if isinstance(node, ft.Type):
            dct['set_args'] = '%(handle)s, %(el_name_get)s' % dct
        else:
            dct['set_args'] = '%(el_name)s' % dct

        if not isinstance(node, ft.Module) or not self.make_package:
            self.write('@property')
        else:
            dct['el_name_get'] = 'get_'+el.name
            dct['el_name_set'] = 'set_'+el.name
            dct['self'] = ''
            dct['selfdot'] = ''
            dct['selfcomma'] = ''
            
        self.write('def %(el_name_get)s(%(self)s):' % dct)
        self.indent()
        self.write(format_doc_string(el))
        self.write('return %(mod_name)s.%(prefix)s%(type_name)s__get__%(el_name)s(%(handle)s)' % dct)
        self.dedent()
        self.write()
        if 'parameter' in el.attributes and isinstance(node, ft.Module) and self.make_package:
            self.write('%(el_name)s = %(el_name_get)s()' % dct)
            self.write()
        
        if 'parameter' not in el.attributes:
            if not isinstance(node, ft.Module) or not self.make_package:
                self.write('@%(el_name_get)s.setter' % dct)
            self.write('''def %(el_name_set)s(%(selfcomma)s%(el_name)s):
    %(mod_name)s.%(prefix)s%(type_name)s__set__%(el_name)s(%(set_args)s)
    ''' % dct)
            self.write()


    def write_dt_wrappers(self, node, el):
        cls_name = ft.strip_type(el.type).title()
        cls_mod_name = self.types[ft.strip_type(el.type)].mod_name
        dct = dict(el_name=el.name,
                   el_name_get=el.name,
                   el_name_set=el.name,                   
                   mod_name=self.f90_mod_name,
                   prefix=self.prefix, type_name=node.name,
                   cls_name=cls_name,
                   cls_mod_name=cls_mod_name+'.',
                   self='self',
                   selfdot='self.',
                   selfcomma='self, ',
                   handle=isinstance(node, ft.Type) and 'self._handle' or '')
        if isinstance(node, ft.Type):
            dct['set_args'] = '%(handle)s, %(el_name)s' % dct
        else:
            dct['set_args'] = '%(el_name)s' % dct
        if self.make_package:
            dct['cls_mod_name'] = ''
            self.imports.add((self.py_mod_name+'.'+cls_mod_name, cls_name))

        if not isinstance(node, ft.Module) or not self.make_package:
            self.write('@property')
        else:
            dct['el_name_get'] = 'get_'+el.name
            dct['el_name_set'] = 'set_'+el.name
            dct['self'] = ''
            dct['selfdot'] = ''
            dct['selfcomma'] = ''
                        
        self.write('def %(el_name_get)s(%(self)s):' % dct)
        self.indent()
        self.write(format_doc_string(el))
        if isinstance(node, ft.Module) and self.make_package:
            self.write('global %(el_name)s' % dct)        
        self.write('''%(el_name)s_handle = %(mod_name)s.%(prefix)s%(type_name)s__get__%(el_name)s(%(handle)s)
if tuple(%(el_name)s_handle) in %(selfdot)s_objs:
    %(el_name)s = %(selfdot)s_objs[tuple(%(el_name)s_handle)]
else:
    %(el_name)s = %(cls_mod_name)s%(cls_name)s.from_handle(%(el_name)s_handle)
    %(selfdot)s_objs[tuple(%(el_name)s_handle)] = %(el_name)s
return %(el_name)s''' % dct)
        self.dedent()
        self.write()

        if 'parameter' not in el.attributes:
            if not isinstance(node, ft.Module) or not self.make_package:
                self.write('@%(el_name_set)s.setter' % dct)
            self.write('''def %(el_name_set)s(%(selfcomma)s%(el_name)s):
    %(el_name)s = %(el_name)s._handle
    %(mod_name)s.%(prefix)s%(type_name)s__set__%(el_name)s(%(set_args)s)
    ''' % dct)
            self.write()

            
    def write_sc_array_wrapper(self, node, el, dims):
        dct = dict(el_name=el.name,
                   el_name_get=el.name,
                   el_name_set=el.name,
                   mod_name=self.f90_mod_name,
                   prefix=self.prefix, type_name=node.name,
                   self='self',
                   selfdot='self.',
                   selfcomma='self, ',
                   doc=format_doc_string(el),
                   handle=isinstance(node, ft.Type) and 'self._handle, ' or '_empty_fortran_t, ')

        if not isinstance(node, ft.Module) or not self.make_package:
            self.write('@property')
        else:
            dct['el_name_get'] = 'get_array_'+el.name
            dct['el_name_set'] = 'set_array_'+el.name
            dct['self'] = ''
            dct['selfdot'] = ''
            dct['selfcomma'] = ''

        self.write('def %(el_name_get)s(%(self)s):' % dct)
        self.indent()
        self.write(format_doc_string(el))
        if isinstance(node, ft.Module) and self.make_package:
            self.write('global %(el_name)s' % dct)        
        self.write("""if '%(el_name_get)s' in %(selfdot)s_arrays:
    %(el_name)s = %(selfdot)s_arrays['%(el_name)s']
else:
    %(el_name)s = get_array(_sizeof_fortran_t,
                            %(handle)s
                            %(mod_name)s.%(prefix)s%(type_name)s__array__%(el_name)s)
    %(selfdot)s_arrays['%(el_name_set)s'] = %(el_name)s
return %(el_name)s""" % dct)
        self.dedent()
        self.write()
        if not isinstance(node, ft.Module) or not self.make_package:
            self.write("@%(el_name)s.setter" % dct)
        self.write("""def %(el_name_set)s(%(selfcomma)s%(el_name)s):
    %(selfdot)s%(el_name)s[...] = %(el_name)s
""" % dct)
        self.write()


    def write_dt_array_wrapper(self, node, el, dims):
        func_name = 'init_array_%s' % el.name
        node.dt_array_initialisers.append(func_name)
        cls_name = ft.strip_type(el.type).title()
        cls_mod_name = self.types[ft.strip_type(el.type)].mod_name

        dct = dict(el_name=el.name,
                   func_name=func_name,
                   type_name=ft.strip_type(el.type).lower(),
                   mod_name=self.f90_mod_name,
                   prefix=self.prefix,
                   self='self',
                   selfdot='self.',
                   parent='self',
                   doc=format_doc_string(el),
                   cls_name=cls_name,
                   cls_mod_name = cls_mod_name+'.')

        if isinstance(node, ft.Module):
            dct['parent'] = '_empty_type'
            dct['selfdot'] = ''
            dct['cls_mod_name'] = ''
        if self.make_package:
            self.imports.add((self.py_mod_name+'.'+cls_mod_name, cls_name))

        self.write('def %(func_name)s(%(self)s):' % dct)
        self.indent()
        if isinstance(node, ft.Module):
            self.write('global %(el_name)s'% dct)
        self.write('''%(selfdot)s%(el_name)s = FortranDerivedTypeArray(%(parent)s,
                                %(mod_name)s.%(prefix)s%(type_name)s__array_getitem__%(el_name)s,
                                %(mod_name)s.%(prefix)s%(type_name)s__array_setitem__%(el_name)s,
                                %(mod_name)s.%(prefix)s%(type_name)s__array_len__%(el_name)s,
                                %(doc)s, %(cls_mod_name)s%(cls_name)s)''' % dct)
        self.write('return %(selfdot)s%(el_name)s' % dct)
        self.dedent()
