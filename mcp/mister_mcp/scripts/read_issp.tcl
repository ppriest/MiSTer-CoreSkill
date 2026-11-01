# Read the core's debug probes over JTAG (In-System Sources and Probes).
#
#   python scripts/read_issp.py [instance] [clear] [set N] [pulse N]
#
# SignalTap acquisition is GUI-only in Quartus Prime Lite 17.0 -- there are no
# *signaltap* Tcl commands -- so ISSP is what a headless workflow can drive.
#
# The probe bus layout is defined where the bus is BUILT (the issp instance in
# the top-level .sv), not here. Keep the field tables in step with it: a
# silently shifted field decodes as plausible nonsense rather than as an error.
#
# Counters typically SATURATE and count per-cycle events, so they pin almost
# immediately: `clear` first and read again for a rate.

# The field tables, `set fields_<id> {{name lo hi format} ...}`: the copy of the core's
# scripts/issp_fields.tcl it registered with the MCP (ISSP_FIELDS), else the file itself.
if {[info exists env(ISSP_FIELDS)]} {
    set tables $env(ISSP_FIELDS)
} else {
    set tables [file join $env(CORE_ROOT) scripts issp_fields.tcl]
}
if {![file exists $tables]} { puts "no $tables -- the core's probe field tables"; exit 1 }
source $tables

# The core's own commands, `proc hook_<name> {idx args}` (KonamiGX's dump and peek): the copy of
# scripts/issp_hooks.tcl it registered (ISSP_HOOKS), else the file itself, if it has one. A hook
# runs after the decode, in the same session, with bits_to_int, write_src and read_probe_data.
if {[info exists env(ISSP_HOOKS)]} {
    source $env(ISSP_HOOKS)
} elseif {[file exists [file join $env(CORE_ROOT) scripts issp_hooks.tcl]]} {
    source [file join $env(CORE_ROOT) scripts issp_hooks.tcl]
}
proc is_hook {w} { expr {[llength [info procs hook_$w]] == 1} }

proc bits_to_int {s lo hi} {
    # read_probe_data returns the bus MSB-first, so index from the right.
    set n [string length $s]
    set v 0
    for {set i $hi} {$i >= $lo} {incr i -1} {
        set c [string index $s [expr {$n - 1 - $i}]]
        set v [expr {$v * 2 + ($c eq "1" ? 1 : 0)}]
    }
    return $v
}

set do_clear [expr {[lsearch -exact $argv "clear"] >= 0}]
# `set N`   : write source byte N (decimal) and leave it
# `pulse N` : write N, then 0 -- for the edge-triggered controls
set set_val -1; set pulse_val -1
set i [lsearch -exact $argv "set"];   if {$i >= 0} { set set_val   [lindex $argv [expr {$i+1}]] }
set i [lsearch -exact $argv "pulse"]; if {$i >= 0} { set pulse_val [lindex $argv [expr {$i+1}]] }

set hw ""
foreach h [get_hardware_names] { if {$hw eq ""} { set hw $h } }
if {$hw eq ""} { puts "NO JTAG HARDWARE FOUND"; exit 1 }
puts "hardware: $hw"

set dev ""
foreach d [get_device_names -hardware_name $hw] {
    if {[string match "*5CSEBA6*" $d] || [string match "*5CSE*" $d] || $dev eq ""} {
        set dev $d
    }
}
if {$dev eq ""} { puts "NO DEVICE FOUND"; exit 1 }
puts "device:   $dev"

# Query instance info BEFORE opening a session: with a session already active
# this fails with "There is already an active In-System Sources and Probes
# session started."
set insts [get_insystem_source_probe_instance_info -hardware_name $hw -device_name $dev]
if {[llength $insts] == 0} {
    puts "NO ISSP INSTANCES -- is this an instrumented build?"
    exit 1
}
foreach i $insts { puts "instance: $i" }

# Arguments: the instance, `clear`, `set N`, `pulse N` in any order, or a hook and everything
# after it as its arguments. Without an instance the first one is read; a named instance that
# is not in the bitstream stops, never falls back.
set want ""
set hook ""
set skip 0
for {set k 0} {$k < [llength $argv]} {incr k} {
    set a [lindex $argv $k]
    if {$skip} { set skip 0; continue }
    if {[is_hook $a]} {
        set hook $a
        set hook_args [lrange $argv [expr {$k + 1}] end]
        # a hook's arguments are its own, not clear/set/pulse
        set do_clear [expr {[lsearch -exact [lrange $argv 0 [expr {$k - 1}]] "clear"] >= 0}]
        set set_val -1; set pulse_val -1
        break
    }
    if {$a eq "set" || $a eq "pulse"} { set skip 1; continue }
    if {$a ne "clear"} { set want $a }
}
set idx [lindex [lindex $insts 0] 0]
set inst_id [lindex [lindex $insts 0] 3]
if {$want ne ""} {
    set found 0
    foreach i $insts {
        if {[lindex $i 3] eq $want} { set idx [lindex $i 0]; set inst_id $want; set found 1 }
    }
    if {!$found} {
        set ids {}
        foreach i $insts { lappend ids [lindex $i 3] }
        puts "instance '$want' is not in this bitstream (it has: $ids)"
        exit 1
    }
}

# The field table belongs to the INSTANCE. An unrecognised id stops rather
# than guesses.
if {[info exists fields_$inst_id]} {
    set fields [set fields_$inst_id]
} else {
    puts "instance id '$inst_id' has no field table in $tables -- add one before reading it"
    exit 1
}
puts "decoding instance $inst_id"

start_insystem_source_probe -device_name $dev -hardware_name $hw
set raw [read_probe_data -instance_index $idx]
# a build whose probe bus has another width can have its own table, fields_<id>_w<bits>
set wtable fields_${inst_id}_w[string length $raw]
if {[info exists $wtable]} { set fields [set $wtable]; puts "table $wtable" }
puts "raw ([string length $raw] bits): $raw"
puts ""

foreach f $fields {
    lassign $f name lo hi fmt
    set v [bits_to_int $raw $lo $hi]
    switch $fmt {
        sdec { if {$v >= 32768} { set v [expr {$v - 65536}] }; puts [format "  %-16s %d" $name $v] }
        hex  { puts [format "  %-16s 0x%08X" $name $v] }
        bit  { puts [format "  %-16s %s"     $name [expr {$v ? "yes" : "no"}]] }
        default { puts [format "  %-16s %d"  $name $v] }
    }
}

# write_source_data takes a BINARY STRING unless -value_in_hex is given; a
# decimal "8" is silently rejected. Every write goes through this, in hex.
proc write_src {idx v} { write_source_data -instance_index $idx -value [format %X $v] -value_in_hex }
if {$set_val >= 0}   { write_src $idx $set_val;   puts "source set to $set_val (reads back 0x[read_source_data -instance_index $idx -value_in_hex])" }
if {$pulse_val >= 0} { write_src $idx $pulse_val; write_src $idx 0; puts "source pulsed $pulse_val" }

if {$do_clear} {
    # Source bit 0 is the counter clear, by convention; the counters are
    # deliberately not reset by the core's own reset.
    write_src $idx 1
    write_src $idx 0
    puts "\ncounters cleared"
}
if {$hook ne ""} {
    puts ""
    hook_$hook $idx {*}$hook_args
}

end_insystem_source_probe
