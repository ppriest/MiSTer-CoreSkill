# Dump every placed atom of a compiled revision: type, location, full hierarchical name.
# Read-only on the post-fit netlist; no re-fit. Run from the directory holding the
# database (build/ for build_staged.py), through scripts/floorplan.py:
#   quartus_cdb -t scripts/floorplan.tcl <revision> <out.tsv>
package require ::quartus::project
package require ::quartus::atoms

set rev [lindex $quartus(args) 0]
set out [lindex $quartus(args) 1]
project_open $rev -revision $rev
read_atom_netlist -type cmp
set f [open $out w]
foreach_in_collection a [get_atom_nodes] {
    set loc [get_atom_node_info -key LOCATION -node $a]
    if {$loc eq ""} continue
    puts $f "[get_atom_node_info -key TYPE -node $a]\t$loc\t[get_atom_node_info -key NAME -node $a]"
}
close $f
project_close
puts "FLOORPLAN_OK"
