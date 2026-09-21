"""cpu.pxd - dichiarazioni di tipo per Cython, lette SOLO in fase di
compilazione (vedi build_cython.py). cpu.py resta un file Python
NORMALE, invariato: continua a funzionare identico se non lo si
compila mai (CPython o PyPy, come sempre), e produce l'identico
risultato se compilato - questo file dice solo al compilatore quali
tipi C usare per gli attributi/metodi che cpu.py gia' definisce, non
cambia la logica di nessuno di essi ("pure Python mode" di Cython,
vedi https://cython.readthedocs.io/en/latest/src/tutorial/pure.html).

Perche' cpu.py e' un buon candidato: i registri (a/x/y/pc/sp/flags)
sono concettualmente interi a 16/24 bit, ma restano oggetti int
Python (allocati/deallocati, con overhead di refcounting) ad ogni
lettura/scrittura - decine di volte per istruzione emulata, in un
loop che nel gioco vero gira ~300-450 volte per frame. Tipizzarli
come interi C elimina quell'overhead senza toccare la logica.

NON tipizzato di proposito: `mem` (bytearray) - acceduto pesantemente
anche FUORI da questo modulo (launcher.py, ppu.py, i test) con
slicing/assegnazione che si aspettano la semantica esatta di
bytearray; un memoryview tipizzato ha semantica leggermente diversa
per l'assegnazione di slice, rischio di rompere qualcosa in silenzio
per un guadagno marginale (mem non e' il collo di bottiglia - lo sono
le operazioni sui registri, ripetute molte piu' volte per istruzione).

NON toccato il meccanismo di dispatch (tabella opcode -> metodo,
vedi step()) - restare fedeli allo stesso identico dict-lookup usato
anche senza Cython, invece di riscriverlo come uno switch, evita di
dover mantenere due logiche diverse a seconda che il modulo sia
compilato o meno."""

cdef class CPU:
    cdef public object mem
    cdef public long a, x, y, pc, sp, flags
    cdef public object stages          # dict {stage: bytes}, popolato dall'host
    cdef public long current_stage, scroll_x, scroll_y
    cdef public list sound_queue
    cdef public object sound_bank      # popolato da launcher.py
                                        # (_load_cart_graphics), non da
                                        # cpu.py stesso - una "cdef
                                        # class" (a differenza di una
                                        # classe Python normale) non
                                        # accetta attributi nuovi al
                                        # volo: ogni attributo assegnato
                                        # dall'esterno va dichiarato
                                        # anche qui, o l'assegnazione
                                        # fallisce con AttributeError
                                        # (bug reale trovato dai test:
                                        # mancava proprio questo)
    cdef public dict _opcode_table

    cpdef long read16(self, long addr)
    cpdef write16(self, long addr, long value)
    cpdef read_mem(self, long addr)
    cpdef write_mem(self, long addr, long value)

    cpdef set_flag(self, long flag, bint condition)
    cpdef update_zn(self, long value)
    cpdef bint flag(self, long f)

    cpdef push(self, long value)
    cpdef long pop(self)

    cpdef _add(self, long operand)
    cpdef _sub(self, long operand)
    cpdef _and(self, long operand)
    cpdef _or(self, long operand)
    cpdef _xor(self, long operand)
    cpdef _cmp(self, long operand)

    cpdef long _imm16(self)
    cpdef long _addr24(self)

    cpdef bint _op_00(self)
    cpdef bint _op_01(self)
    cpdef bint _op_10(self)
    cpdef bint _op_11(self)
    cpdef bint _op_12(self)
    cpdef bint _op_13(self)
    cpdef bint _op_14(self)
    cpdef bint _op_15(self)
    cpdef bint _op_16(self)
    cpdef bint _op_17(self)
    cpdef bint _op_18(self)
    cpdef bint _op_20(self)
    cpdef bint _op_21(self)
    cpdef bint _op_22(self)
    cpdef bint _op_23(self)
    cpdef bint _op_24(self)
    cpdef bint _op_25(self)
    cpdef bint _op_30(self)
    cpdef bint _op_31(self)
    cpdef bint _op_32(self)
    cpdef bint _op_33(self)
    cpdef bint _op_34(self)
    cpdef bint _op_35(self)
    cpdef bint _op_40(self)
    cpdef bint _op_41(self)
    cpdef bint _op_42(self)
    cpdef bint _op_43(self)
    cpdef bint _op_44(self)
    cpdef bint _op_45(self)
    cpdef bint _op_50(self)
    cpdef bint _op_51(self)
    cpdef bint _op_52(self)
    cpdef bint _op_53(self)
    cpdef bint _op_54(self)
    cpdef bint _op_55(self)
    cpdef bint _op_56(self)
    cpdef bint _op_57(self)
    cpdef bint _op_60(self)
    cpdef bint _op_61(self)
    cpdef bint _op_62(self)
    cpdef bint _op_63(self)
    cpdef bint _op_64(self)
    cpdef bint _op_65(self)
    cpdef bint _op_66(self)
    cpdef bint _op_67(self)
    cpdef bint _op_68(self)
    cpdef bint _op_70(self)
    cpdef bint _op_71(self)
    cpdef bint _op_72(self)
    cpdef bint _op_73(self)
    cpdef bint _op_74(self)
    cpdef bint _op_75(self)
    cpdef bint _op_80(self)
    cpdef bint _op_90(self)
    cpdef bint _op_91(self)

    cpdef _build_opcode_table(self)
    cpdef bint step(self)
    cpdef long run(self, long start_pc, long input_byte=*, extra_inputs=*, long max_steps=*)
    cpdef state_checksum(self)
