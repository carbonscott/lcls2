"""Detector interfaces for timetool data (`tt_raw_2_0_0`, `ttdet_ttalg_0_0_1`) and parsers for the
frame format read by `ttdet_ttalg_0_0_1`.
"""
import numpy as np
from psana.detector.detector_impl import DetectorImpl
from amitypes import Array1d

class tt_raw_2_0_0(DetectorImpl):
    """Detector interface for detector type `tt`, software `raw`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super().__init__(*args)
        self._add_fields()

    def _info(self,evt):
        # check for missing data
        segments = self._segments(evt)
        if segments is None: return None
        return segments[0]

# leftover from when we wrote out the EventBatcher format.
# still used at the moment in the self-tests
class ttdet_ttalg_0_0_1(DetectorImpl):
    """Detector interface for detector type `ttdet`, software `ttalg`, version 0.0.1.

    The code comment calls it a leftover from the EventBatcher format that the self-tests still use;
    `parsed_frame` parses segment 0's `data` with `timeToolParser`.
    """
    def __init__(self, *args):
        super(ttdet_ttalg_0_0_1, self).__init__(*args)

    def _image(self,evt):
        # check for missing data
        segments = self._segments(evt)
        if segments is None: return None
        # seems reasonable to assume that all timetool data comes from one segment
        return segments[0].data

    def _header(self,evt):                           #take out.  scientists don't care about this. 
        # check for missing data
        segments = self._segments(evt)
        if segments is None: return None
        # seems reasonable to assume that all timetool data comes from one segment
        return segments[0].data[:16]
    
    def parsed_frame(self,evt):
        """Parse the bytes of segment 0's `data` with a new `timeToolParser` and return the parser.

        No missing-data check: raises TypeError if the event does not have all of this detector's
        segments.
        """
        pFrame = timeToolParser()
        p = self._segments(evt)[0].data.tobytes()
        pFrame._parseData(p)

        return pFrame

    def image(self, evt) -> Array1d:
        """Return the `prescaled_frame` of `parsed_frame(evt)`: the tdest-2 frame as an int8 numpy array, or None if there is none."""
        parsed_frame_object = self.parsed_frame(evt)
        return parsed_frame_object.prescaled_frame

    #def edge_value(self,evt):              #speak with damiani for how to send back this data to ami
    #def edge_uncertainty(self,evt):        #needs _(underscore) to hide things AMI doesn't need to see.
    #

class eventBuilderParser():
    """Parser for a frame made of a header and sub-frames, each sub-frame followed by a 16-byte trailer.

    The private `_parseArray` walks the sub-frames from the end of the buffer, reading each size from
    the first two bytes (little-endian) and the tdest from byte 4 of the trailer after it; sub-frames
    whose first two bytes match the main header are parsed recursively as nested frames.
    """
    def __init__(self):        
        return

    def _frames_to_position(self,frame_bytearray,position):
        return int('0b'+'{0:08b}'.format(frame_bytearray[position+1])+'{0:08b}'.format(frame_bytearray[position]),2)
    
    def _checkForSubframes(self):
        self._sub_is_fullframe = [False]*len(self._frame_list)
        
        for i in range(len(self._frame_list)):
            
            if self._main_header[:2] == self._frame_list[i][:self._HEADER_WIDTH ][:2]:
                self._sub_is_fullframe[i] = True
        
        return
    
    def _resolveSubFrames(self):
        self._checkForSubframes()
        self._sub_frames = [False]*len(self._frame_list)
        for i in range(len(self._frame_list)):
            if self._sub_is_fullframe[i]:
                self._sub_frames[i] =  eventBuilderParser()
                #print("length = ",len(self._frame_list[i]))
                self._sub_frames[i]._parseArray(self._frame_list[i])
                self._frame_list[i] = False
        return
    
    def print_info(self):
        """Print every attribute except `_frame_list` and bytearray values, then the info of each nested sub-frame parser."""
        for i in self.__dict__:
            if i != "_frame_list" and type(self.__dict__[i]) is not bytearray:
                print(i," = ",self.__dict__[i])
                
        for i in range(len(self._sub_is_fullframe)):
            if(self._sub_is_fullframe[i]):
                print("\nsubframe = ",i)
                self._sub_frames[i].print_info()
                
        return
        
    def _parseArray(self,frame_bytearray:bytearray):
        self._frame_bytes     = len(frame_bytearray)
        self._main_header     = frame_bytearray[0:16]

        self._version                = self._main_header[0] & int('00001111', 2)
        self._axi_stream_bit_width   = 8*2**((self._main_header[0] >> 4) + 1)
        self.sequence_count         = self._main_header[1]
        self._HEADER_WIDTH           = int(self._axi_stream_bit_width/8)
        
        
        self._frame_sizes_reversed         = [self._frames_to_position(frame_bytearray,-16)]
        self._frame_positions_reversed     = [[self._frame_bytes-16-self._frame_sizes_reversed[0],self._frame_bytes-16]] #[start, and]
        self._frame_list                   = [frame_bytearray[self._frame_positions_reversed[-1][0]:self._frame_positions_reversed[-1][1]]]
        
        self._tdest                        = [frame_bytearray[-12]]
        
        
        parsed_frame_size = sum(self._frame_sizes_reversed) +(len(self._frame_sizes_reversed)+1)*self._HEADER_WIDTH
        #print("parsing")
        while len(frame_bytearray)>=(parsed_frame_size+self._HEADER_WIDTH):
            #print(len(frame_bytearray))
            self._frame_sizes_reversed.append(self._frames_to_position(frame_bytearray,self._frame_positions_reversed[-1][0]-16))
            
            self._frame_positions_reversed.append([self._frame_positions_reversed[-1][0]-16-self._frame_sizes_reversed[-1],self._frame_positions_reversed[-1][0]-16]) #[start, and]            
            
            self._frame_list.append(frame_bytearray[self._frame_positions_reversed[-1][0]:self._frame_positions_reversed[-1][1]])
            self._tdest.append(frame_bytearray[self._frame_positions_reversed[-1][1]+4])
            
            
          
            parsed_frame_size = sum(self._frame_sizes_reversed) +(len(self._frame_sizes_reversed)+1)*self._HEADER_WIDTH
        
        #self._sub_is_fullframe = [False]*len(self._frame_list)
        self._resolveSubFrames()
        
        return
    
class timeToolParser(eventBuilderParser):
    """`eventBuilderParser` whose `_parseData` also extracts the timetool items from the parsed frame.

    It sets the timing bus (frame with tdest 0, or None), `edge_position` (16-bit value from the
    tdest-0 entry of the tdest-1 frame; IndexError if absent), `background_frame` (tdest-1 entry of
    that frame, or None) and `prescaled_frame` (tdest-2 frame as int8 array, or None).
    """
    def _parseData(self,frame_bytearray:bytearray):
        self._parseArray(frame_bytearray)
        
        
        try:
            _timing_bus_idx           = [i[0] for i in enumerate(self._tdest) if i[1]==0][0] #timing bus always has _tdest of 0
            self._timing_bus          = self._frame_list[_timing_bus_idx]  #frame_bytearray[16:32]
        except IndexError:
            self._timing_bus = None
        
        sub_frame_idx            = [i[0] for i in enumerate(self._tdest) if i[1]==1][0]
        edge_pos_idx             = [i[0] for i in enumerate(self._sub_frames[sub_frame_idx]._tdest) if i[1]==0][0]
        self.edge_position       = self._sub_frames[sub_frame_idx]._frame_list[edge_pos_idx][0] + self._sub_frames[sub_frame_idx]._frame_list[edge_pos_idx][1]*256
        
        try:
            bkg_frame_idx            = [i[0] for i in enumerate(self._sub_frames[sub_frame_idx]._tdest) if i[1]==1][0]
            self.background_frame    = self._sub_frames[sub_frame_idx]._frame_list[bkg_frame_idx]
        except IndexError:    
            self.background_frame    = None

        try:
            prescaled_frame_idx      = [i[0] for i in enumerate(self._tdest) if i[1]==2][0]
            #self.prescaled_frame    = self._frame_list[prescaled_frame_idx] 
            self.prescaled_frame     = np.frombuffer(self._frame_list[prescaled_frame_idx],dtype = np.int8)
            
        except IndexError:
            self.prescaled_frame     = None
            
        
        
        
    
        return
