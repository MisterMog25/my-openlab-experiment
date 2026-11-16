from shutil import move
from tuke_openlab import Controller
from tuke_openlab.lights import Color
from random import randint
import time
from queue import Empty

class Lamp(object):
    def __init__(self):
        
        self.top_right = [1, 28, 55]
        self.top_left = [27, 54, 81]

        self.current_row = 1
        self.current_position = 1

    def random_color(self) -> tuple:
        return randint(0, 255), randint(0, 255), randint(0, 255)

    def random_intesity(self) -> int:
        return randint(0, 255)
    
    def lamp_on(self, controller: Controller, index : int):
        colors = self.random_color()
        controller.lights.set_color(index, Color(colors[0], colors[1], colors[2], self.random_intesity()))
        
    def lamp_off(self, controller: Controller, index : int):
        controller.lights.set_color(index, Color(0, 0, 0))
        
    
    def move_left(self, controller : Controller, action_funk, current_position : int) -> int:
        
        time.sleep(0.1)
        
        #дізналися межі нашого ряду й який він по рахунку
        top_right = 0
        top_left = 0
        for i in range(3):
            if(current_position >= self.top_right[i] and current_position <= self.top_left[i]):
                top_left = self.top_left[i]
                top_right = self.top_right[i]
        
        #якщо ми не з самого ліва - рухаємося на ліво
        #якщо лампа ввікнена - вимикаємо, якщо ні, рухаємо й вмикаємо випадкови колір
        if(current_position < top_left):
            current_position += 1
            action_funk(controller, current_position)
            return current_position
        else:
            return None

    def move_right(self, controller : Controller, action_funk, current_position : int) -> int:
        
        time.sleep(0.1)
        
        #дізналися межі нашого ряду й який він по рахунку
        top_right = 0
        top_left = 0
        for i in range(3):
            if(current_position >= self.top_right[i] and current_position <= self.top_left[i]):
                top_left = self.top_left[i]
                top_right = self.top_right[i]

        #якщо ми не з самого ліва - рухаємося на ліво
        #якщо лампа ввікнена - вимикаємо, якщо ні, рухаємо й вмикаємо випадкови колір
        if(current_position > top_right):
            current_position -= 1
            action_funk(controller, current_position)
            return current_position
        else:
            return None
            
    def move_up(self, controller : Controller, action_funk, current_position : int) -> int:
        
        time.sleep(0.1)
        
        if( not (current_position <= self.top_left[0] and current_position >= self.top_right[0])):
            current_position -= 27
            action_funk(controller, current_position)
            return current_position
        else:
            return None

    def move_down(self, controller : Controller, action_funk, current_position : int) -> int:
        
        time.sleep(0.1)
        
        if( not (current_position <= self.top_left[2] and current_position >= self.top_right[2])):
            current_position += 27
            action_funk(controller, current_position)
            return current_position
        else:
            return None




    def draw_rectangle(self, controller : Controller, first_start = 1, second_start = 81):

        self.lamp_on(controller, first_start)
        self.lamp_on(controller, second_start)
        
        
        prew_first = first_start
        prew_second = second_start
        
        while(True):
            first_start = self.move_left(controller, self.lamp_on, first_start)
            second_start = self.move_right(controller, self.lamp_on, second_start)
            
            if(first_start is None or second_start is None):
                first_start = prew_first
                second_start = prew_second
                break

            prew_first = first_start
            prew_second = second_start 
            
        while(True):
            first_start = self.move_down(controller, self.lamp_on, first_start)
            second_start = self.move_up(controller, self.lamp_on, second_start)
            
            if(first_start is None or second_start is None):
                first_start = prew_first   
                second_start = prew_second
                break

            prew_first = first_start 
            prew_second = second_start

        while(True):
            first_start = self.move_up(controller, self.lamp_off, first_start)
            second_start = self.move_down(controller, self.lamp_off, second_start)

            if(first_start is None or second_start is None):
                first_start = prew_first
                second_start = prew_second
                break

            prew_first = first_start 
            prew_second = second_start



        while(True):
            first_start = self.move_right(controller, self.lamp_off, first_start)
            second_start = self.move_left(controller, self.lamp_off, second_start)

            if(first_start is None or second_start is None):
                first_start = prew_first
                second_start = prew_second
                break

            prew_first = first_start
            prew_second = second_start


    
    
    
    
    
    def draw_wave_to_the_right(self, controller : Controller, action_funk_move, action_funk_lamp, start = 81, rec_checker = True, commands = None):
        
        go_up = True
        
        up_down = self.move_up
        
        start_erasing = start
        
        prew = start
        start = action_funk_move(controller, action_funk_lamp, start) 
        
        
        while(start != None):
            
            time.sleep(0.2)
            
            if(go_up):
                prew = start
                start = self.move_up(controller, action_funk_lamp, start)
                if(start is None):
                    go_up = False
                    start = prew
            else:
                prew = start
                start = self.move_down(controller, action_funk_lamp, start)
                if(start is None):
                    go_up = True
                    start = prew
        
            prew = start                    
            start = action_funk_move(controller, action_funk_lamp, start)

        if(rec_checker == True):
            self.draw_wave_to_the_right(controller, self.move_right, self.lamp_off, start_erasing, False)



    def turn_on_all(self, controller : Controller, action_funk, checker = True):
        
        start_index = 81
        prew_start = start_index
        
        action_funk(controller, start_index)
        
        start_index = self.move_right(controller, action_funk, start_index)
        
        while(True):
            
            time.sleep(0.2)
            
            while (start_index != None):
                prew_start = start_index
                start_index = self.move_up(controller, action_funk, start_index)
            
            start_index = prew_start    
            start_index = self.move_right(controller, action_funk, start_index)
            
            if(start_index == None):
                break

            while (start_index != None):
                prew_start = start_index
                start_index = self.move_down(controller, action_funk, start_index)

            start_index = prew_start
            start_index = self.move_right(controller, action_funk, start_index)

            if(start_index == None):
                break

        
        if checker:
            self.turn_on_all(controller, self.lamp_off, False)



    def all_lamps_off(self, controller : Controller):
        controller.lights.turn_off()
    
    
    def process_commands(self, controller : Controller, commands):
        while(True):
            
            command = commands.get()

            if(command == "r"):
                self.draw_rectangle(controller)

            if(command == "w"):
                self.draw_wave_to_the_right(controller, self.move_right, self.lamp_on)
                
            if(command == "a"):
                self.turn_on_all(controller, self.lamp_on)
                
            if(command == "c"):
                self.all_lamps_off(controller)
                
            if(command == "o"):
                self.all_lamps_off(controller)
                return
        
        
        
        
        
        
            
        
        
                
            
