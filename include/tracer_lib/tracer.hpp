#pragma once

#include <iostream>
#include <vector>
#include <cmath>

#include "tracer_lib/sphere.hpp"
#include "tracer_lib/color.hpp"

namespace tracer {

class vect {

    std::vector<double> m_coords{};

public:

    vect (double coord_1, double coord_2, double coord_3) {
        std::vector<double> new_coords{coord_1, coord_2, coord_3};
        m_coords = new_coords;
    }

    vect& operator=(const vect& other) {
        m_coords = other.m_coords;
        return *this;
    }
    
    vect* operator*(const vect& other) {
        m_coords
    }
    vect& operator*(double number) {
        for (auto&& coord : m_coords) {
            coord *= number;
        }
        return *this;
    }
};

class Tracer_t {

public:

private:


};

}